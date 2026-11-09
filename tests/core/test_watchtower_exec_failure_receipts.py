"""Execution failure receipts are bounded, principal-scoped and sanitized."""
import unittest

from gway_remote.watchtower_exec_failure_receipts import FailureReceipts, ExecutionStageError


class FailureReceiptsTests(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.receipts = FailureReceipts(clock=lambda: self.now[0])
        self.request = "a" * 32

    def test_scope_is_principal_specific(self):
        self.assertTrue(self.receipts.record(self.request, "owner", "bridge_dispatch"))
        self.assertEqual(self.receipts.inspect(self.request, "owner"),
                         {"request_id": self.request, "status": "failure",
                          "stage": "bridge_dispatch"})
        self.assertEqual(self.receipts.inspect(self.request, "other")["status"], "unknown")

    def test_other_principal_cannot_overwrite_receipt(self):
        self.receipts.record(self.request, "owner", "pinned_transport")
        self.assertFalse(self.receipts.record(self.request, "other", "ssh_transport"))
        self.assertEqual(self.receipts.inspect(self.request, "owner")["stage"], "pinned_transport")

    def test_expiry_is_unknown_not_success(self):
        self.receipts.record(self.request, "owner", "ssh_transport")
        self.now[0] += 301
        self.assertEqual(self.receipts.inspect(self.request, "owner")["status"], "unknown")

    def test_no_arbitrary_stage_or_secret_payload(self):
        self.assertFalse(self.receipts.record(self.request, "owner", "password=secret"))
        self.assertEqual(self.receipts.inspect(self.request, "owner")["status"], "unknown")

    def test_bounded_storage_evicts_oldest_receipt(self):
        for n in range(513):
            self.assertTrue(self.receipts.record(f"{n:032x}", "owner", "bridge_dispatch"))
        self.assertEqual(len(self.receipts._rows), 512)
        self.assertEqual(self.receipts.inspect(f"{0:032x}", "owner")["status"], "unknown")
        self.assertEqual(self.receipts.inspect(f"{512:032x}", "owner")["status"], "failure")

    def test_stage_marker_only_accepts_known_origin(self):
        self.assertEqual(ExecutionStageError("pinned_transport").stage, "pinned_transport")
        with self.assertRaises(ValueError):
            ExecutionStageError("ssh_password")

    def test_invalid_request_id_fails_closed(self):
        with self.assertRaises(ValueError):
            self.receipts.inspect("invalid", "owner")

    def test_unknown_outcome_never_claims_failure(self):
        self.receipts.record(self.request, "owner", "bridge_dispatch", "unknown")
        self.assertEqual(self.receipts.inspect(self.request, "owner")["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
