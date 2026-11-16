"""D1-B3-A differential tests: private temporary SQLite vs pure D1-B1.

Never production authority. Does not change V1-C1/C2 or spawn node workloads.
Expected semantic differences are explicit assertions, not normalized away.
"""
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import sqlite3
import tempfile
import unittest

from gway_remote.go_diagnostic_coordinator_d1b1 import (
    ModelError, Snapshot, State, Witness, finish, observe, recovery_preview, reserve,
)
from gway_remote.maintenance_fence_provenance import BootSample
from gway_remote.maintenance_fence_store import OfflineFenceJournal, StoreError

BOOT = "boot-alpha-01"
SHA = "a" * 40
PRINCIPAL = "b" * 24
RESOURCE = ("node/gway-001",)


def request(token="c", *, lease=1000, boot=BOOT, resource=RESOURCE, sha=SHA):
    ident = token * 32
    binding = dict(node="gway-001", repo="arthexis/ocpp-simulator",
                   sha=sha, verified_principal=PRINCIPAL, source="schedule",
                   request_id=ident, boot_id=boot, lease_until_ns=lease)
    witness = Witness(PRINCIPAL, binding["node"], binding["repo"], sha,
                      binding["source"], ident, BootSample(boot, 100), resource)
    return binding, witness


class DifferentialJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "fence.sqlite"
        self.store = OfflineFenceJournal.initialize(self.path)

    def c1_reserve(self, binding, witness, *, now=100):
        return self.store.reserve(resources=witness.resources, now_ns=now, **binding)

    def pair(self, token="c", **kwargs):
        binding, witness = request(token, **kwargs)
        model, model_receipt = reserve(Snapshot(), binding, witness)
        journal_receipt = self.c1_reserve(binding, witness)
        self.assertEqual((model_receipt.state.value, model_receipt.generation),
                         (journal_receipt["state"], journal_receipt["generation"]))
        return binding, witness, model, journal_receipt

    def test_initial_and_idempotent_same_binding(self):
        b, w, model, c1 = self.pair()
        again, response = reserve(model, b, w)
        self.assertIs(again, model)
        self.assertEqual(response.reason, "idempotent")
        self.assertEqual(self.c1_reserve(b, w), c1)
        self.assertEqual(OfflineFenceJournal(self.path).inspect(b["request_id"]), c1)

    def test_conflicting_whole_node_reservations_rejected(self):
        _, _, model, c1 = self.pair()
        b2, w2 = request("d")
        with self.assertRaises(ModelError):
            reserve(model, b2, w2)
        with self.assertRaises(StoreError):
            self.c1_reserve(b2, w2)
        self.assertEqual(self.store.inspect("c" * 32), c1)

    def test_generation_monotonic_for_disjoint_children(self):
        b1, w1 = request(resource=("node/gway-001/deploy/simulator",))
        model, _ = reserve(Snapshot(), b1, w1)
        c1 = self.c1_reserve(b1, w1)
        b2, w2 = request("d", resource=("node/gway-001/deploy/reports",))
        model, result = reserve(model, b2, w2)
        persisted = self.c1_reserve(b2, w2)
        self.assertEqual((result.generation, persisted["generation"]), (2, 2))
        self.assertEqual(model.generation, 2)
        self.assertEqual(c1["generation"], 1)

    def test_changed_request_binding_rejected_both(self):
        b, w, model, _ = self.pair()
        changed = {**b, "sha": "d" * 40}
        with self.assertRaises(ModelError):
            reserve(model, changed, replace(w, sha="d" * 40))
        with self.assertRaises(StoreError):
            self.c1_reserve(changed, replace(w, sha="d" * 40))

    def test_expiry_observe_parity_after_explicit_observation(self):
        b, _, model, _ = self.pair()
        model, response = observe(model, b["request_id"],
                                  sample=BootSample(BOOT, 1001))
        changed = self.store.observe(now_ns=1001, boot_id=BOOT)
        self.assertEqual(changed, 1)
        c1 = self.store.inspect(b["request_id"])
        self.assertEqual((model.records[0].state.value, response.state.value, c1["state"]),
                         ("uncertain", "uncertain", "uncertain"))
        self.assertEqual((model.records[0].generation, c1["generation"]), (1, 1))
        b2, w2 = request("d", lease=2000)
        with self.assertRaises(ModelError):
            reserve(model, b2, w2)
        with self.assertRaises(StoreError):
            self.c1_reserve(b2, w2, now=1001)

    def test_boot_change_parity_when_observed_explicitly(self):
        b, _, model, _ = self.pair()
        model, result = observe(model, b["request_id"],
                                sample=BootSample("boot-alpha-02", 200))
        self.assertEqual(result.reason, "boot_changed")
        self.assertEqual(self.store.observe(now_ns=200, boot_id="boot-alpha-02"), 1)
        self.assertEqual(self.store.inspect(b["request_id"])["state"], "uncertain")
        self.assertEqual(model.records[0].state, State.UNCERTAIN)

    def test_divergence_c1_reserve_records_expiry_automatically(self):
        b, w, model, _ = self.pair()
        rival, witness = request("d", lease=2000)
        with self.assertRaises(StoreError):
            self.c1_reserve(rival, witness, now=1001)
        self.assertEqual(self.store.inspect(b["request_id"])["state"], "uncertain")
        self.assertEqual(model.records[0].state, State.HELD)  # expected divergence
        with self.assertRaises(ModelError):
            reserve(model, rival, witness)
        observed, _ = observe(model, b["request_id"],
                              sample=BootSample(BOOT, 1001))
        self.assertEqual(observed.records[0].state, State.UNCERTAIN)

    def test_divergence_c1_retry_after_expiry_changes_state(self):
        b, w, model, original = self.pair()
        c1 = self.c1_reserve(b, w, now=1001)
        self.assertEqual(c1["state"], "uncertain")
        unchanged, result = reserve(model, b, w)
        self.assertIs(unchanged, model)
        self.assertEqual(result.state, State.HELD)  # expected divergence
        self.assertNotEqual(c1["receipt_digest"], original["receipt_digest"])

    def test_crash_before_commit_rollback_and_after_commit_reopen(self):
        b, w = request()
        proposal, _ = reserve(Snapshot(), b, w)
        # Explicit transaction not committed: closing drops the provisional row.
        db = sqlite3.connect(self.path)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE meta SET value='19' WHERE key='generation'")
        finally:
            db.close()
        self.assertEqual(self.c1_reserve(b, w)["generation"], 1)
        reopened = OfflineFenceJournal(self.path)
        self.assertEqual(reopened.inspect(b["request_id"])["state"], "held")
        self.assertEqual(proposal.records[0].state, State.HELD)
        b2, w2 = request("d")
        with self.assertRaises(StoreError):
            reopened.reserve(resources=w2.resources, now_ns=100, **b2)

    def test_recovery_divergence_admin_tombstone_vs_preview(self):
        b, _, model, _ = self.pair()
        model, _ = observe(model, b["request_id"], sample=BootSample(BOOT, 1001))
        self.store.observe(now_ns=1001, boot_id=BOOT)
        previous = self.store.inspect(b["request_id"])
        self.assertEqual(recovery_preview(model, b["request_id"],
                         expected_generation=1, admin_attested=True,
                         quiescence_attested=True), "offline_recovery_preconditions_only")
        terminal = self.store.recover(
            request_id=b["request_id"], expected_digest=previous["receipt_digest"],
            verified_admin="d" * 24, evidence_digest="e" * 64)
        self.assertEqual((terminal["state"], terminal["generation"]), ("terminal", 2))
        self.assertEqual(model.records[0].state, State.UNCERTAIN)
        self.assertEqual(model.generation, 1)
        with self.assertRaises(StoreError):
            self.store.recover(request_id=b["request_id"],
                               expected_digest=previous["receipt_digest"],
                               verified_admin="d" * 24, evidence_digest="e" * 64)

    def test_missing_clean_finish_event_in_c1_is_explicit(self):
        b, _, model, _ = self.pair()
        terminal, r = finish(model, b["request_id"], generation=1,
                             sample=BootSample(BOOT, 200),
                             children_reaped=True, workspace_removed=True)
        self.assertEqual((r.state, terminal.records[0].state),
                         (State.TERMINAL, State.TERMINAL))
        self.assertEqual(self.store.inspect(b["request_id"])["state"], "held")
        with sqlite3.connect(self.path) as db:
            events = [row[0] for row in db.execute("SELECT event FROM journal")]
        self.assertEqual(events, ["reserved"])
        # No mapping to recover(), which requires an actual uncertain record.

    def test_journal_small_capacity_fixture_is_fail_closed(self):
        # Test-only bound is lowered; production constant and code unchanged.
        b, w = request()
        with patch("gway_remote.maintenance_fence_store._MAX_JOURNAL_EVENTS", 1):
            persisted = self.c1_reserve(b, w)
            self.assertEqual(persisted["state"], "held")
            with self.assertRaises(StoreError):
                self.store.observe(now_ns=1001, boot_id=BOOT)
            with self.assertRaises(StoreError):
                self.c1_reserve(*request("d", lease=2000), now=1001)
            reopened = OfflineFenceJournal(self.path)
            self.assertEqual(reopened.inspect(b["request_id"]), persisted)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM journal").fetchone()[0], 1)
        model, _ = reserve(Snapshot(), b, w)
        bounded = replace(model, events=4096)
        with self.assertRaises(ModelError):
            observe(bounded, b["request_id"], sample=BootSample(BOOT, 1001))

    def test_request_id_format_divergence_is_rejected_not_converted(self):
        # D0 accepts human-readable IDs; C1/C2 require exactly 32 hex chars.
        from gway_remote.go_diagnostic_contract import DiagnosticPlan
        plan = DiagnosticPlan(request_id="diagnostic-01", simulator_sha=SHA,
                              remote_sha="d" * 40,
                              workspace="/tmp/go-diag-diagnostic-01")
        plan.validate()
        b, w = request()
        invalid = {**b, "request_id": "diagnostic-01"}
        with self.assertRaises(StoreError):
            self.c1_reserve(invalid, w)
        with self.assertRaises(ModelError):
            reserve(Snapshot(), invalid, replace(w, request_id="diagnostic-01"))

    def test_sqlite_path_audit_cannot_prove_future_open_identity(self):
        # Documented TOCTOU: no intentional path swap or privileged operations.
        from gway_remote.maintenance_fence_storage_policy import audit_private_sqlite
        report = audit_private_sqlite(self.temp.name, "fence.sqlite")
        self.assertIn("fence.sqlite", report.checked)
        # Report is point-in-time and contains no pinned sqlite connection.
        self.assertFalse(hasattr(report, "connection"))


if __name__ == "__main__":
    unittest.main()
