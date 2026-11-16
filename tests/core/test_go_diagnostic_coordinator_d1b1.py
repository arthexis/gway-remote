"""D1-B1 hermetic, adversarial, deterministic tests; no node or subprocess."""
import unittest
from dataclasses import replace

from gway_remote.go_diagnostic_coordinator_d1b1 import (
    MAX_EVENTS, ModelError, Receipt, Snapshot, State, Witness, check_order,
    finish, observe, recovery_preview, reserve,
)
from gway_remote.maintenance_fence_provenance import BootSample

SIM_SHA = "67e2d0e0fef704d7c693a6bd86af29bcc60db9a5"
REMOTE_SHA = "d980bac526678c01452ea7b8864de145b7571b35"
BOOT = "boot-12345678"
PRINCIPAL = "a" * 24
REQ = "b" * 32
RESOURCES = ("node/gway-001",)


def case(*, request=REQ, sha=SIM_SHA, principal=PRINCIPAL,
         boot=BOOT, now=100, lease=900, resources=RESOURCES):
    binding = {
        "node": "gway-001", "repo": "arthexis/ocpp-simulator",
        "sha": sha, "verified_principal": principal,
        "source": "manual", "request_id": request,
        "boot_id": boot, "lease_until_ns": lease,
    }
    witness = Witness(
        principal, "gway-001", "arthexis/ocpp-simulator", sha,
        "manual", request, BootSample(boot, now), resources,
    )
    return binding, witness


class CoordinatorD1B1Tests(unittest.TestCase):
    def rejects(self, fn):
        with self.assertRaises(ModelError):
            fn()

    def test_pure_reserve_and_sanitized_receipt(self):
        b, w = case()
        original = Snapshot()
        new, receipt = reserve(original, b, w)
        self.assertEqual(original.records, ())
        self.assertEqual((new.events, new.generation), (1, 1))
        self.assertEqual(receipt.state, State.HELD)
        self.assertEqual(set(receipt.sanitized()), {
            "schema", "state", "reason", "generation", "request_id"
        })
        self.assertNotIn("principal", str(receipt.sanitized()))

    def test_idempotent_reuse_without_duplicate_event(self):
        b, w = case()
        state, _ = reserve(Snapshot(), b, w)
        again, receipt = reserve(state, b, w)
        self.assertIs(again, state)
        self.assertEqual(receipt.reason, "idempotent")

    def test_request_replay_with_changed_binding_fails(self):
        b, w = case()
        state, _ = reserve(Snapshot(), b, w)
        other, _ = case(sha=REMOTE_SHA)
        self.rejects(lambda: reserve(state, other, replace(w, sha=REMOTE_SHA)))

    def test_competing_whole_node_claim_fails(self):
        b, w = case()
        state, _ = reserve(Snapshot(), b, w)
        rival, rw = case(request="c" * 32)
        self.rejects(lambda: reserve(state, rival, rw))
        self.assertEqual(state.events, 1)

    def test_disjoint_nodes_are_only_conceptually_independent(self):
        b, w = case()
        state, _ = reserve(Snapshot(), b, w)
        other, ow = case(request="c" * 32, resources=("node/gway-002",))
        other["node"] = "gway-002"
        ow = replace(ow, node="gway-002")
        result, _ = reserve(state, other, ow)
        self.assertEqual((len(result.records), result.generation), (2, 2))

    def test_malformed_resource_and_ancestor_duplicates_reject(self):
        b, w = case()
        for resources in (
            ("node:gway-001:compute",),
            ("node/gway-001", "node/gway-001/deploy/ocpp-simulator"),
            ("node/gway-001", "node/gway-001"),
            ("node/gway-001/deploy/z", "node/gway-001/deploy/a"),
            ("node/gway-001/deploy/ocpp-simulator", "node/gway-001"),
        ):
            self.rejects(lambda: reserve(Snapshot(), b, replace(w, resources=resources)))

    def test_untrusted_binding_never_verifies_itself(self):
        b, w = case()
        for changed in (
            {"verified_principal": "c" * 24},
            {"sha": REMOTE_SHA},
            {"boot_id": "boot-abcdefgh"},
            {"node": "gway-002"},
            {"lease_until_ns": 50},
        ):
            forged = {**b, **changed}
            self.rejects(lambda: reserve(Snapshot(), forged, w))

    def test_wrong_witness_request_is_rejected(self):
        b, w = case()
        self.rejects(lambda: reserve(Snapshot(), b, replace(w, request_id="c" * 32)))

    def test_expired_lease_stays_uncertain_and_conflicting(self):
        b, w = case()
        state, _ = reserve(Snapshot(), b, w)
        state, receipt = observe(state, REQ, sample=BootSample(BOOT, 901))
        self.assertEqual((state.events, receipt.state), (2, State.UNCERTAIN))
        rival, rw = case(request="c" * 32)
        self.rejects(lambda: reserve(state, rival, rw))
        self.rejects(lambda: finish(state, REQ, generation=1,
                                    sample=BootSample(BOOT, 902),
                                    children_reaped=True, workspace_removed=True))

    def test_boot_change_never_clears_resources(self):
        b, w = case()
        state, _ = reserve(Snapshot(), b, w)
        state, receipt = observe(state, REQ,
                                 sample=BootSample("newboot123", 200))
        self.assertEqual(receipt.reason, "boot_changed")
        self.assertEqual(state.records[0].state, State.UNCERTAIN)

    def test_stale_generation_cannot_finish(self):
        b, w = case()
        state, _ = reserve(Snapshot(), b, w)
        self.rejects(lambda: finish(state, REQ, generation=0,
                                    sample=BootSample(BOOT, 200),
                                    children_reaped=True, workspace_removed=True))

    def test_live_children_or_cleanup_unknown_fail_closed(self):
        b, w = case()
        initial, _ = reserve(Snapshot(), b, w)
        for reaped, cleaned in ((False, True), (True, False), (None, True)):
            result, receipt = finish(initial, REQ, generation=1,
                                     sample=BootSample(BOOT, 200),
                                     children_reaped=reaped, workspace_removed=cleaned)
            self.assertEqual(receipt.state, State.UNCERTAIN)
            self.assertEqual(result.records[0].state, State.UNCERTAIN)
            self.assertEqual(initial.records[0].state, State.HELD)

    def test_clean_completion_is_only_offline_terminal(self):
        b, w = case()
        state, _ = reserve(Snapshot(), b, w)
        result, receipt = finish(state, REQ, generation=1,
                                 sample=BootSample(BOOT, 200),
                                 children_reaped=True, workspace_removed=True)
        self.assertEqual(receipt.state, State.TERMINAL)
        rival, rw = case(request="c" * 32)
        result, _ = reserve(result, rival, rw)
        self.assertEqual(result.generation, 2)

    def test_crash_model_snapshot_retains_claim(self):
        b, w = case()
        persisted, _ = reserve(Snapshot(), b, w)
        copy = Snapshot(persisted.records, persisted.generation, persisted.events)
        rival, rw = case(request="c" * 32)
        self.rejects(lambda: reserve(copy, rival, rw))

    def test_recovery_requires_admin_and_quiescence_but_does_not_mutate(self):
        b, w = case()
        state, _ = reserve(Snapshot(), b, w)
        state, _ = observe(state, REQ, sample=BootSample(BOOT, 901))
        self.rejects(lambda: recovery_preview(state, REQ, expected_generation=1,
                                               quiescence_attested=False, admin_attested=True))
        self.rejects(lambda: recovery_preview(state, REQ, expected_generation=0,
                                               quiescence_attested=True, admin_attested=True))
        self.assertEqual(recovery_preview(state, REQ, expected_generation=1,
                                          quiescence_attested=True, admin_attested=True),
                         "offline_recovery_preconditions_only")
        self.assertEqual(state.records[0].state, State.UNCERTAIN)

    def test_capacity_exhaustion_denies_new_event(self):
        b, w = case()
        empty_full = Snapshot(events=MAX_EVENTS)
        self.rejects(lambda: reserve(empty_full, b, w))
        active, _ = reserve(Snapshot(), b, w)
        full = replace(active, events=MAX_EVENTS)
        self.rejects(lambda: observe(full, REQ, sample=BootSample(BOOT, 901)))
        rival, rw = case(request="c" * 32)
        self.rejects(lambda: reserve(full, rival, rw))

    def test_no_partial_reservation_on_bad_snapshot(self):
        b, w = case()
        invalid = Snapshot(generation=1, events=1,
                           records=(replace(reserve(Snapshot(), b, w)[0].records[0],
                                            resources=("node/gway-001", "node/gway-001/deploy/x")),))
        self.rejects(lambda: reserve(invalid, b, w))

    def test_lock_order_rejects_cycles_duplicates_unknowns(self):
        self.assertEqual(check_order(("github_queue", "node_coordinator",
                                      "sqlite_transaction", "legacy_flock",
                                      "side_effect"))[-1], "side_effect")
        for order in (
            ("legacy_flock", "sqlite_transaction"), ("node_coordinator", "node_coordinator"),
            ("side_effect", "github_queue"), ("unknown",),
        ):
            self.rejects(lambda: check_order(order))

    def test_observe_no_clock_change_is_idempotent(self):
        b, w = case()
        state, _ = reserve(Snapshot(), b, w)
        same, receipt = observe(state, REQ, sample=BootSample(BOOT, 200))
        self.assertIs(state, same)
        self.assertEqual(receipt.reason, "unchanged")


if __name__ == "__main__":
    unittest.main()
