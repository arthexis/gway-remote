"""Offline adversarial tests for #561 MaintenanceFence V1-A (no real lock)."""
from dataclasses import replace
import unittest

from gway_remote.maintenance_fence_contract import (
    Claim, Fence, FenceError, Receipt, acquire, advance, make_claim, observe,
    recover, token_for,
)

BASE = dict(node="gway-001", repo="arthexis/ocpp-simulator",
            sha="a" * 40, verified_principal="b" * 24,
            source="schedule", request_id="c" * 32, boot_id="boot-alpha-01",
            generation=1, lease_until_ns=1000)


def claim(**changes):
    return make_claim(**{**BASE, **changes})


class MaintenanceFenceContractTests(unittest.TestCase):
    def held(self):
        return acquire(Fence(), claim(), now_ns=100)

    def test_acquisition_and_idempotent_duplicate(self):
        held = self.held()
        self.assertEqual(held.state, "held")
        self.assertEqual(held.receipt.event, "acquired")
        self.assertIs(acquire(held, claim(), now_ns=200), held)
        self.assertEqual(held.receipt.digest, self.held().receipt.digest)

    def test_competing_principals_requests_sources_and_sha_are_uncertain(self):
        held = self.held()
        variants = (
            {"verified_principal": "d" * 24},
            {"request_id": "e" * 32},
            {"source": "manual"},
            {"sha": "f" * 40},
            {"boot_id": "boot-alpha-02"},
            {"generation": 2},
            {"node": "gway-002"},
        )
        for change in variants:
            with self.subTest(change=change):
                rival = claim(**change)
                result = acquire(held, rival, now_ns=200)
                self.assertEqual(result.state, "uncertain")
                self.assertEqual(acquire(result, claim(), now_ns=250), result)

    def test_expiration_and_boot_change_fail_closed(self):
        held = self.held()
        self.assertEqual(observe(held, now_ns=1000).state, "uncertain")
        self.assertEqual(observe(held, now_ns=200, observed_boot_id="boot-alpha-02").state, "uncertain")
        self.assertEqual(advance(held, claim(), action="complete", now_ns=1000).state, "uncertain")
        self.assertEqual(acquire(held, claim(), now_ns=1000).state, "uncertain")
        self.assertEqual(observe(held, now_ns=999).state, "held")

    def test_stale_fencing_token_and_tamper_are_rejected(self):
        held = self.held()
        bad = replace(claim(), token="0" * 64)
        for operation in (
            lambda: acquire(held, bad, now_ns=200),
            lambda: advance(held, bad, now_ns=200, action="complete"),
        ):
            with self.assertRaises(FenceError):
                operation()
        stale = claim(generation=2)
        self.assertEqual(advance(held, stale, now_ns=200, action="complete").state, "uncertain")

    def test_renewal_monotonic_and_stale_lease(self):
        held = self.held()
        for new in (0, 1000, 999, True, "1100"):
            with self.subTest(new=new), self.assertRaises(FenceError):
                advance(held, claim(), now_ns=200, action="renew", lease_until_ns=new)
        renewed = advance(held, claim(), now_ns=200, action="renew", lease_until_ns=1500)
        self.assertEqual(renewed.claim.lease_until_ns, 1500)
        self.assertEqual(renewed.claim.token, held.claim.token)
        self.assertEqual(advance(renewed, claim(), now_ns=300, action="complete").state, "uncertain")
        self.assertEqual(advance(renewed, replace(claim(), lease_until_ns=1500),
                                 now_ns=300, action="complete").state, "terminal")

    def test_crash_uncertain_and_terminal_immutable(self):
        held = self.held()
        uncertain = advance(held, claim(), now_ns=300, action="fault")
        self.assertEqual(uncertain.state, "uncertain")
        self.assertIs(advance(uncertain, claim(), now_ns=300, action="complete"), uncertain)
        terminal = advance(held, claim(), now_ns=300, action="complete")
        self.assertEqual(terminal.receipt.event, "completed")
        self.assertIs(acquire(terminal, claim(generation=2), now_ns=400), terminal)
        self.assertIs(advance(terminal, claim(), now_ns=400, action="fault"), terminal)

    def test_administrative_recovery_requires_exact_receipt_and_fresh_generation(self):
        uncertain = observe(self.held(), now_ns=1000)
        digest = uncertain.receipt.digest
        kwargs = dict(verified_admin="d" * 24, expected_generation=1,
                      expected_digest=digest, new_generation=2)
        for altered in (
            {"verified_admin": "invalid"},
            {"expected_generation": 2},
            {"expected_digest": "0" * 64},
            {"new_generation": 1},
            {"new_generation": True},
        ):
            with self.subTest(altered=altered), self.assertRaises(FenceError):
                recover(uncertain, **{**kwargs, **altered})
        tombstone = recover(uncertain, **kwargs)
        self.assertEqual(tombstone.state, "terminal")
        self.assertEqual(tombstone.generation, 2)
        self.assertEqual(tombstone.receipt.event, "recovered")
        with self.assertRaises(FenceError):
            recover(tombstone, **kwargs)
        self.assertIs(acquire(tombstone, claim(generation=3), now_ns=200), tombstone)

    def test_invalid_identity_and_corrupt_receipts_rejected(self):
        for changes in (
            {"node": "../gway"},
            {"repo": "repository"},
            {"sha": "a" * 39},
            {"verified_principal": "A" * 24},
            {"verified_principal": True},
            {"request_id": "c" * 31},
            {"source": "untrusted"},
            {"boot_id": ""},
            {"generation": 0},
            {"generation": True},
            {"lease_until_ns": -1},
        ):
            with self.subTest(changes=changes), self.assertRaises(FenceError):
                claim(**changes)
        held = self.held()
        with self.assertRaises(FenceError):
            replace(held.receipt, digest="bad")
        with self.assertRaises(FenceError):
            replace(held, generation=3)
        with self.assertRaises(FenceError):
            replace(held, state="terminal")
        with self.assertRaises(FenceError):
            Fence(state="held")
        with self.assertRaises(FenceError):
            acquire(Fence(), claim(), now_ns=True)

    def test_claim_receipt_cross_binding_and_digest_integrity(self):
        held = self.held()
        receipt = held.receipt
        changes = (
            {"digest": "0" * 64},
            {"request_id": "d" * 32},
            {"reason": "lease_extended"},
            {"event": "renewed", "reason": "lease_extended"},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(FenceError):
                replace(held, receipt=replace(receipt, **change))
        with self.assertRaises(FenceError):
            replace(held, claim=replace(held.claim, request_id="d" * 32))
        with self.assertRaises(FenceError):
            replace(held, claim=replace(held.claim, token="0" * 64))
        # The snapshot and its internally consistent digest can be forged by
        # an attacker; these checks are not authentication.
        self.assertEqual(receipt.request_id, held.claim.request_id)

    def test_invalid_event_state_and_recovery_metadata(self):
        held = self.held()
        for change in (
            {"event": "recovered"},
            {"event": "completed"},
            {"state": "terminal"},
            {"reason": "success"},
            {"previous_digest": "0" * 64},
            {"admin": "e" * 24},
        ):
            with self.subTest(change=change), self.assertRaises(FenceError):
                replace(held.receipt, **change)
        with self.assertRaises(FenceError):
            Receipt("recovered", "terminal", 2, "c" * 32,
                    "administrative_recovery", "0" * 64)
        uncertain = observe(held, now_ns=1000)
        recovered = recover(uncertain, verified_admin="e" * 24,
                            expected_generation=1,
                            expected_digest=uncertain.receipt.digest,
                            new_generation=2)
        for change in (
            {"previous_digest": "0" * 64},
            {"admin": "f" * 24},
            {"digest": "0" * 64},
            {"reason": "success"},
        ):
            with self.subTest(recovery=change), self.assertRaises(FenceError):
                replace(recovered, receipt=replace(recovered.receipt, **change))

    def test_repo_segments_reject_dotdot_and_hidden_prefix(self):
        for repo in ("../repo", "owner/..", "owner/.", "./repo",
                     "owner/.hidden", "-owner/repo", "owner/-repo"):
            with self.subTest(repo=repo), self.assertRaises(FenceError):
                claim(repo=repo)
        self.assertEqual(claim(repo="arthexis/gway-remote").repo,
                         "arthexis/gway-remote")

    def test_digest_binds_lease_and_boot_and_receipt(self):
        held = self.held()
        renewed = advance(held, claim(), now_ns=200, action="renew", lease_until_ns=1600)
        self.assertNotEqual(held.receipt.digest, renewed.receipt.digest)
        self.assertNotEqual(token_for(node=BASE["node"], repo=BASE["repo"],
                                      sha=BASE["sha"], principal=BASE["verified_principal"],
                                      source=BASE["source"], request_id=BASE["request_id"],
                                      boot_id="boot-alpha-02", generation=1), held.claim.token)


if __name__ == "__main__":
    unittest.main()
