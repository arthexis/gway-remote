"""Hermetic V1-C1 storage tests: no node, deployment or workflow access."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import multiprocessing
import os
import sqlite3
import tempfile
import unittest

from gway_remote.maintenance_fence_store import OfflineFenceJournal, StoreError

NODE = "gway-001"
SIMULATOR = "node/gway-001/deploy/ocpp-simulator"
NETWORK = "node/gway-001/network/nftables"
REPORTS = "node/gway-001/deploy/ocpp-reports"



def _separate_process_reserve(path, request_id, gate, output):
    """Separate interpreter/process/connection, never a simulated thread."""
    gate.wait(timeout=15)
    try:
        receipt = OfflineFenceJournal(path).reserve(
            resources=(SIMULATOR,), now_ns=100, node=NODE,
            repo="arthexis/ocpp-simulator", sha="a" * 40,
            verified_principal="b" * 24, source="schedule",
            request_id=request_id, boot_id="boot-alpha-01", lease_until_ns=1000)
        output.put(("held", receipt["generation"]))
    except StoreError:
        output.put(("denied", None))


def _commit_then_lose_reply(path):
    """Simulate process death AFTER a committed reservation, before reply."""
    OfflineFenceJournal(path).reserve(
        resources=(SIMULATOR,), now_ns=100, node=NODE,
        repo="arthexis/ocpp-simulator", sha="a" * 40,
        verified_principal="b" * 24, source="schedule",
        request_id="c" * 32, boot_id="boot-alpha-01", lease_until_ns=1000)
    os._exit(0)


class OfflineJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "fence.sqlite"
        self.store = OfflineFenceJournal.initialize(self.path)

    def request(self, ident="c", *, resources=(SIMULATOR,), boot="boot-alpha-01",
                now=100, lease=1000, **changes):
        args = dict(node=NODE, repo="arthexis/ocpp-simulator",
                    sha="a" * 40, verified_principal="b" * 24,
                    source="schedule", request_id=ident * 32,
                    boot_id=boot, lease_until_ns=lease)
        args.update(changes)
        return self.store.reserve(resources=resources, now_ns=now, **args)

    def sql(self, statement, params=()):
        with sqlite3.connect(self.path) as db:
            db.execute(statement, params)
            db.commit()

    def test_idempotent_same_payload_survives_reopen(self):
        first = self.request()
        self.assertEqual(first["state"], "held")
        self.assertEqual(first, self.request())
        self.assertEqual(first, OfflineFenceJournal(self.path).inspect("c" * 32))
        self.assertEqual(first["generation"], 1)

    def test_duplicate_request_different_identity_rejected(self):
        self.request()
        for changes in ({"lease": 2000}, {"boot": "boot-alpha-02"},
                        {"repo": "arthexis/ocpp-csms"}, {"source": "manual"},
                        {"sha": "f" * 40}, {"verified_principal": "d" * 24},
                        {"resources": (REPORTS,)}):
            with self.subTest(changes=changes), self.assertRaises(StoreError):
                self.request(**changes)

    def test_atomic_conflict_and_independent_siblings(self):
        self.request()
        with self.assertRaises(StoreError):
            self.request("d")
        other = self.request("e", resources=(REPORTS,))
        self.assertEqual(other["generation"], 2)
        with self.assertRaises(StoreError):
            self.request("f", resources=("node/gway-001",))
        with self.assertRaises(StoreError):
            self.request("f", resources=(SIMULATOR, NETWORK))

    def test_thread_race_one_winner(self):
        def run(token):
            try:
                return self.request(token)
            except StoreError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(run, ("d", "e")))
        self.assertEqual(sum(x is not None for x in outcomes), 1)
        self.assertEqual(self.store.inspect("d" * 32)["generation"] if outcomes[0]
                         else self.store.inspect("e" * 32)["generation"], 1)

    def test_boot_change_is_uncertain_and_blocks_competition(self):
        self.request()
        self.assertEqual(self.store.observe(now_ns=200, boot_id="boot-alpha-02"), 1)
        self.assertEqual(self.store.inspect("c" * 32)["state"], "uncertain")
        self.assertEqual(self.store.observe(now_ns=300, boot_id="boot-alpha-02"), 0)
        with self.assertRaises(StoreError):
            self.request("d", boot="boot-alpha-02")
        self.assertEqual(self.request()["state"], "uncertain")

    def test_expiry_is_uncertain_never_auto_release(self):
        self.request()
        self.assertEqual(self.store.observe(now_ns=1000, boot_id="boot-alpha-01"), 1)
        with self.assertRaises(StoreError):
            self.request("d", now=1001, lease=2000)
        self.assertEqual(self.store.inspect("c" * 32)["state"], "uncertain")

    def test_exact_duplicate_after_expiry_records_uncertain(self):
        self.request()
        stale = self.request(now=1100, lease=1000)
        self.assertEqual(stale["state"], "uncertain")
        self.assertEqual(self.store.inspect("c"*32)["state"], "uncertain")
        with self.assertRaises(StoreError):
            self.request("d", now=1100, lease=2000)

    def test_expiration_during_new_request_keeps_reservation(self):
        self.request()
        with self.assertRaises(StoreError):
            self.request("d", now=1100, lease=2000)
        # Conflict is denied, but the observed expiry is committed BEFORE
        # returning the error; the journal survives reopen unchanged.
        self.assertEqual(self.store.inspect("c" * 32)["state"], "uncertain")
        self.assertEqual(OfflineFenceJournal(self.path).inspect("c" * 32)["state"],
                         "uncertain")
        self.assertEqual(self.store.observe(now_ns=1100, boot_id="boot-alpha-01"), 0)
        with self.assertRaises(StoreError):
            self.request("d", now=1100, lease=2000)

    def test_boot_change_during_denied_request_persists_uncertain(self):
        self.request()
        with self.assertRaises(StoreError):
            self.request("d", boot="boot-alpha-02", now=200)
        self.assertEqual(self.store.inspect("c" * 32)["state"], "uncertain")
        self.assertEqual(self.store.observe(now_ns=200, boot_id="boot-alpha-02"), 0)

    def test_two_independent_processes_one_owner(self):
        ctx = multiprocessing.get_context("spawn")
        gate = ctx.Barrier(2)
        output = ctx.Queue()
        workers = [ctx.Process(target=_separate_process_reserve,
                               args=(str(self.path), token * 32, gate, output))
                   for token in ("d", "e")]
        try:
            for child in workers:
                child.start()
            for child in workers:
                child.join(timeout=20)
                self.assertEqual(child.exitcode, 0)
            outcomes = [output.get(timeout=3), output.get(timeout=3)]
            self.assertEqual(sorted(x[0] for x in outcomes), ["denied", "held"])
            self.assertEqual([x[1] for x in outcomes if x[0] == "held"], [1])
        finally:
            for child in workers:
                if child.is_alive():
                    child.terminate()
                    child.join(timeout=5)
            output.close()

    def test_commit_survives_lost_reply_without_new_generation(self):
        ctx = multiprocessing.get_context("spawn")
        child = ctx.Process(target=_commit_then_lose_reply, args=(str(self.path),))
        try:
            child.start()
            child.join(timeout=20)
            self.assertEqual(child.exitcode, 0)
        finally:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        original = self.store.inspect("c" * 32)
        self.assertEqual(original["generation"], 1)
        self.assertEqual(original["state"], "held")
        self.assertEqual(self.request(), original)
        with self.assertRaises(StoreError):
            self.request(lease=2000)

    def test_bounded_journal_replay_with_many_independent_resources(self):
        for i in range(1, 65):
            self.request(resources=(f"node/gway-001/deploy/resource-{i}",),
                         request_id=f"{i:032x}")
        reopened = OfflineFenceJournal(self.path)
        self.assertEqual(reopened.inspect(f"{64:032x}")["generation"], 64)
        self.assertEqual(self.store.inspect(f"{1:032x}")["generation"], 1)

    def test_exact_4096_4097_journal_limit_and_rollback(self):
        """Boundary fixture uses valid chained records; no 4095 slow API replays.

        At capacity, both conflicting admission and observed expiry reject
        without mutating the terminal journal record or its receipt.
        """
        from gway_remote.maintenance_fence_store import _MAX_JOURNAL_EVENTS
        self.assertEqual(_MAX_JOURNAL_EVENTS, 4096)
        # Build a legitimate historical chain in one atomic transaction.
        # Every resource is a distinct sibling, preserving replay invariants.
        db = self.store._open()
        try:
            last = ""
            for i in range(1, 4096):
                req = f"{i:032x}"
                binding = dict(node=NODE, repo="arthexis/ocpp-simulator",
                               sha="a" * 40, verified_principal="b" * 24,
                               source="schedule", request_id=req,
                               boot_id="boot-alpha-01", lease_until_ns=1000)
                snap = {"binding": binding,
                        "resources": [f"node/gway-001/deploy/resource-{i}"],
                        "state": "held", "generation": i,
                        "reason": "reserved", "admin": None,
                        "evidence_digest": None}
                last = self.store._append(db, i, last, "reserved", snap)
            db.execute("UPDATE meta SET value=? WHERE key='generation'", ("4095",))
            db.commit()
        finally:
            db.close()

        # Event 4096 is allowed and fully committed.
        last_request = f"{4096:032x}"
        resource = "node/gway-001/deploy/resource-4096"
        receipt = self.request(request_id=last_request, resources=(resource,))
        self.assertEqual(receipt["generation"], 4096)
        self.assertEqual(receipt["state"], "held")
        self.assertEqual(self.store.inspect(last_request), receipt)
        # Duplicate at full capacity does not append or advance generation.
        self.assertEqual(self.request(request_id=last_request, resources=(resource,)),
                         receipt)

        # Event 4097 must reject and roll back *all* tentative changes.
        with self.assertRaises(StoreError):
            self.request(request_id=f"{4097:032x}",
                         resources=("node/gway-001/deploy/resource-4097",))
        # Observing expiry at capacity also fails closed; not even an
        # uncertain journal entry or receipt may be partially committed.
        with self.assertRaises(StoreError):
            self.store.observe(now_ns=1000, boot_id="boot-alpha-01")

        reopened = OfflineFenceJournal(self.path)
        self.assertEqual(reopened.inspect(last_request), receipt)
        with sqlite3.connect(self.path) as check:
            self.assertEqual(check.execute("SELECT COUNT(*) FROM journal").fetchone()[0], 4096)
            self.assertEqual(check.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0],
                             "4096")
            self.assertEqual(check.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 4096)
            self.assertEqual(check.execute(
                "SELECT COUNT(*) FROM journal WHERE seq=4097").fetchone()[0], 0)
            self.assertEqual(check.execute(
                "SELECT payload, receipt_digest FROM requests WHERE request_id=?",
                (last_request,)).fetchone(),
                check.execute(
                    "SELECT payload, digest FROM journal WHERE seq=4096").fetchone())
        self.assertEqual(self.request(request_id=last_request, resources=(resource,)),
                         receipt)

    def test_admin_recovery_requires_exact_receipt_and_evidence(self):
        self.request()
        self.store.observe(now_ns=1000, boot_id="boot-alpha-01")
        before = self.store.inspect("c" * 32)
        kwargs = dict(request_id="c" * 32,
                      expected_digest=before["receipt_digest"],
                      verified_admin="d" * 24, evidence_digest="e" * 64)
        for change in ({"expected_digest": "0" * 64},
                       {"verified_admin": "bad"}, {"evidence_digest": "bad"},
                       {"request_id": "f" * 32}):
            with self.subTest(change=change), self.assertRaises(StoreError):
                self.store.recover(**{**kwargs, **change})
        terminal = self.store.recover(**kwargs)
        self.assertEqual(terminal["state"], "terminal")
        self.assertEqual(terminal["generation"], 2)
        with self.assertRaises(StoreError):
            self.store.recover(**kwargs)
        self.assertEqual(self.request()["state"], "terminal")
        next_claim = self.request("d", now=100, lease=2000)
        self.assertEqual(next_claim["generation"], 3)

    def test_crash_before_sql_commit_rolls_back(self):
        self.request()
        db = sqlite3.connect(self.path)
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE meta SET value='999' WHERE key='generation'")
        db.close()  # simulate abrupt connection loss before commit
        self.assertEqual(self.store.inspect("c" * 32)["generation"], 1)

    def test_corrupt_journal_digest_fails_closed(self):
        self.request()
        self.sql("UPDATE journal SET digest=? WHERE seq=1", ("0" * 64,))
        with self.assertRaises(StoreError):
            self.store.inspect("c" * 32)
        with self.assertRaises(StoreError):
            self.request("d", resources=(REPORTS,))

    def test_corrupt_rows_and_counter_fail_closed(self):
        for mutation in (
            ("UPDATE requests SET receipt_digest=? ", ("0" * 64,)),
            ("UPDATE meta SET value='0' WHERE key='generation'", ()),
            ("DELETE FROM journal WHERE seq=1", ()),
        ):
            with self.subTest(mutation=mutation[0]):
                with tempfile.TemporaryDirectory() as t:
                    j = OfflineFenceJournal.initialize(Path(t) / "db.sqlite")
                    j.reserve(resources=(SIMULATOR,), now_ns=100,
                              node=NODE, repo="arthexis/ocpp-simulator", sha="a"*40,
                              verified_principal="b"*24, source="schedule",
                              request_id="c"*32, boot_id="boot-alpha-01",
                              lease_until_ns=1000)
                    with sqlite3.connect(j.path) as db:
                        db.execute(*mutation)
                        db.commit()
                    with self.assertRaises(StoreError):
                        j.inspect("c"*32)

    def test_invalid_paths_and_schema_fail_closed(self):
        with self.assertRaises(StoreError):
            OfflineFenceJournal(self.path.parent / "does-not-exist.sqlite").inspect("c"*32)
        with self.assertRaises(StoreError):
            OfflineFenceJournal.initialize(self.path)
        with self.assertRaises(StoreError):
            self.request(resources=("node/gway-002",))
        with self.assertRaises(StoreError):
            self.request(resources=())
        with self.assertRaises(StoreError):
            self.request(request_id="short")
        with self.assertRaises(StoreError):
            self.request(now=True)
        with self.assertRaises(StoreError):
            self.request(lease=90)
        self.request()
        self.sql("DELETE FROM meta WHERE key='version'")
        with self.assertRaises(StoreError):
            self.request("d", resources=(REPORTS,))


if __name__ == "__main__":
    unittest.main()
