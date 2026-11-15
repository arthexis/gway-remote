"""D1-B2: adversarial, deterministic offline interleaving and failure tests.

No threads, clocks, disk, node, process launches or production runners.
Demonstrates that pure snapshots are NOT an atomic distributed coordinator:
a durable external compare-and-swap / transaction is still required.
"""
import itertools
import unittest
from dataclasses import replace

from gway_remote.go_diagnostic_coordinator_d1b1 import (
    MAX_EVENTS, MAX_GENERATION, ModelError, Reservation, Snapshot, State,
    Witness, check_order, finish, observe, recovery_preview, reserve,
)
from gway_remote.maintenance_fence_provenance import BootSample

BOOT = "boot-12345678"
SHA = "67e2d0e0fef704d7c693a6bd86af29bcc60db9a5"
PRINCIPAL = "a" * 24


def request(key, *, node="gway-001", resource=None, lease=900):
    request_id = key * 32
    resources = (resource or f"node/{node}",)
    binding = {
        "node": node, "repo": "arthexis/ocpp-simulator", "sha": SHA,
        "verified_principal": PRINCIPAL, "source": "manual",
        "request_id": request_id, "boot_id": BOOT, "lease_until_ns": lease,
    }
    witness = Witness(
        PRINCIPAL, node, "arthexis/ocpp-simulator", SHA,
        "manual", request_id, BootSample(BOOT, 100), resources)
    return binding, witness


class InterleavingAndCrashTests(unittest.TestCase):
    def rejects(self, op):
        with self.assertRaises(ModelError):
            op()

    def test_every_serial_order_refuses_conflicting_second_reservation(self):
        # Simulates one shared, atomically committed snapshot; not actual locking.
        for order in itertools.permutations(("b", "c")):
            with self.subTest(order=order):
                snap = Snapshot()
                first, witness = request(order[0])
                snap, receipt = reserve(snap, first, witness)
                self.assertEqual((receipt.generation, snap.events), (1, 1))
                second, witness2 = request(order[1])
                self.rejects(lambda: reserve(snap, second, witness2))
                self.assertEqual((len(snap.records), snap.events), (1, 1))

    def test_stale_read_exposes_absent_linearizability(self):
        # Both calls succeed against the same empty value: they MUST NOT be
        # accepted as two committed reservations. An external transactional
        # compare-and-swap must reject one stale proposal.
        empty = Snapshot()
        a, wa = request("b")
        b, wb = request("c")
        proposal_a, ra = reserve(empty, a, wa)
        proposal_b, rb = reserve(empty, b, wb)
        self.assertEqual((ra.state, rb.state), (State.HELD, State.HELD))
        self.assertEqual(proposal_a.generation, proposal_b.generation)
        self.assertNotEqual(proposal_a.records, proposal_b.records)
        self.assertEqual(empty, Snapshot())
        self.rejects(lambda: reserve(proposal_a, b, wb))

    def test_crash_before_commit_leaves_only_previous_durable_snapshot(self):
        durable = Snapshot()
        a, wa = request("b")
        proposed, _ = reserve(durable, a, wa)
        # Proposed update vanished before persistence.
        self.assertEqual(durable, Snapshot())
        self.assertNotEqual(proposed, durable)
        b, wb = request("c")
        next_durable, _ = reserve(durable, b, wb)
        self.assertEqual(next_durable.records[0].binding()["request_id"], "c" * 32)

    def test_crash_after_commit_keeps_held_claim_and_denies_competitor(self):
        a, wa = request("b")
        durable, receipt = reserve(Snapshot(), a, wa)
        self.assertEqual(receipt.reason, "reserved")
        replay = Snapshot(tuple(durable.records), durable.generation, durable.events)
        b, wb = request("c")
        self.rejects(lambda: reserve(replay, b, wb))
        self.assertEqual(replay.records[0].state, State.HELD)

    def test_interleaved_expiry_before_competitor_keeps_uncertainty(self):
        b, wb = request("b")
        snap, _ = reserve(Snapshot(), b, wb)
        stale = snap
        snap, receipt = observe(snap, "b" * 32, sample=BootSample(BOOT, 901))
        self.assertEqual(receipt.state, State.UNCERTAIN)
        c, wc = request("c")
        self.rejects(lambda: reserve(snap, c, wc))
        # Old snapshot is stale even though its owner still says HELD;
        # it is not an execution permit or valid replacement for 'snap'.
        self.assertEqual(stale.records[0].state, State.HELD)
        self.assertEqual(snap.records[0].state, State.UNCERTAIN)

    def test_interleaved_boot_change_after_crash_remains_blocked(self):
        b, wb = request("b")
        durable, _ = reserve(Snapshot(), b, wb)
        recovered = Snapshot(durable.records, durable.generation, durable.events)
        uncertain, result = observe(recovered, "b" * 32,
                                    sample=BootSample("boot-restarted-123", 110))
        self.assertEqual(result.reason, "boot_changed")
        c, wc = request("c")
        self.rejects(lambda: reserve(uncertain, c, wc))
        self.rejects(lambda: finish(uncertain, "b" * 32, generation=1,
                                    sample=BootSample("boot-restarted-123", 120),
                                    children_reaped=True, workspace_removed=True))

    def test_live_child_forces_uncertain_even_if_workspace_removed(self):
        b, wb = request("b")
        snap, _ = reserve(Snapshot(), b, wb)
        uncertain, receipt = finish(snap, "b" * 32, generation=1,
                                    sample=BootSample(BOOT, 120),
                                    children_reaped=False, workspace_removed=True)
        self.assertEqual(receipt.state, State.UNCERTAIN)
        c, wc = request("c")
        self.rejects(lambda: reserve(uncertain, c, wc))
        self.assertEqual(uncertain.records[0].children_reaped, False)

    def test_cleanup_failure_followed_by_administrative_preview_does_not_unlock(self):
        b, wb = request("b")
        snap, _ = reserve(Snapshot(), b, wb)
        uncertain, _ = finish(snap, "b" * 32, generation=1,
                              sample=BootSample(BOOT, 130),
                              children_reaped=True, workspace_removed=False)
        self.rejects(lambda: recovery_preview(
            uncertain, "b" * 32, expected_generation=1,
            quiescence_attested=False, admin_attested=True))
        self.assertEqual(recovery_preview(
            uncertain, "b" * 32, expected_generation=1,
            quiescence_attested=True, admin_attested=True),
            "offline_recovery_preconditions_only")
        c, wc = request("c")
        self.rejects(lambda: reserve(uncertain, c, wc))

    def test_recovery_preview_rejects_stale_generation_and_missing_admin(self):
        b, wb = request("b")
        held, _ = reserve(Snapshot(), b, wb)
        uncertain, _ = observe(held, "b" * 32, sample=BootSample(BOOT, 901))
        for generation, admin, quiet in (
            (0, True, True), (2, True, True), (1, False, True),
            (1, True, False), (1, 1, True),
        ):
            with self.subTest(generation=generation, admin=admin, quiet=quiet):
                self.rejects(lambda: recovery_preview(
                    uncertain, "b" * 32, expected_generation=generation,
                    admin_attested=admin, quiescence_attested=quiet))

    def test_full_journal_denies_expiry_transition_and_new_request(self):
        b, wb = request("b")
        held, _ = reserve(Snapshot(), b, wb)
        exhausted = replace(held, events=MAX_EVENTS)
        self.rejects(lambda: observe(exhausted, "b" * 32,
                                     sample=BootSample(BOOT, 901)))
        c, wc = request("c")
        self.rejects(lambda: reserve(exhausted, c, wc))
        self.assertEqual(exhausted.records[0].state, State.HELD)
        self.assertEqual(exhausted.events, MAX_EVENTS)

    def test_full_journal_rejects_clean_finish_without_releasing(self):
        b, wb = request("b")
        held, _ = reserve(Snapshot(), b, wb)
        full = replace(held, events=MAX_EVENTS)
        self.rejects(lambda: finish(full, "b" * 32, generation=1,
                                    sample=BootSample(BOOT, 120),
                                    children_reaped=True, workspace_removed=True))
        self.assertEqual(full.records[0].state, State.HELD)

    def test_generation_overflow_blocks_new_reservation(self):
        at_limit = Snapshot(generation=MAX_GENERATION, events=0)
        b, wb = request("b")
        self.rejects(lambda: reserve(at_limit, b, wb))

    def test_overlapping_injected_reservations_are_invalid_snapshot(self):
        b, wb = request("b")
        first, _ = reserve(Snapshot(), b, wb)
        c, wc = request("c")
        rival, _ = reserve(Snapshot(), c, wc)
        malformed = Snapshot(records=(first.records[0], rival.records[0]),
                             generation=1, events=2)
        self.rejects(lambda: reserve(malformed, request("d")[0], request("d")[1]))

    def test_disjoint_two_node_interleavings_do_not_lose_updates_when_serial(self):
        for order in itertools.permutations(("gway-001", "gway-002")):
            snap = Snapshot()
            for i, node in enumerate(order):
                binding, witness = request("b" if i == 0 else "c", node=node)
                snap, _ = reserve(snap, binding, witness)
            self.assertEqual((snap.events, snap.generation, len(snap.records)), (2, 2, 2))

    def test_lock_order_and_coverage_are_not_physical_attestation(self):
        order = ("github_queue", "node_coordinator", "sqlite_transaction",
                 "legacy_flock", "side_effect")
        self.assertEqual(check_order(order), order)
        for bad in (
            ("node_coordinator", "github_queue"),
            ("legacy_flock", "sqlite_transaction"),
            ("legacy_flock", "legacy_flock"),
        ):
            self.rejects(lambda: check_order(bad))
        # The returned tuple does not create or hold any lock.

    def test_receipt_remains_sanitized_after_uncertain_fault(self):
        b, wb = request("b")
        snap, _ = reserve(Snapshot(), b, wb)
        _, receipt = observe(snap, "b" * 32,
                             sample=BootSample("boot-restarted-123", 120))
        serialized = receipt.sanitized()
        self.assertEqual(serialized["state"], "uncertain")
        self.assertEqual(set(serialized),
                         {"schema", "state", "reason", "generation", "request_id"})
        self.assertNotIn(PRINCIPAL, str(serialized))
        self.assertNotIn("stdout", str(serialized))


if __name__ == "__main__":
    unittest.main()
