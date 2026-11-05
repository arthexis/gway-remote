"""Manual deployment broker admission and durable receipt tests."""
import os
from pathlib import Path
import tempfile
import unittest

from gway_remote.manual_deploy_broker import authorize_deploy, DeploymentReceipts

SHA = "a" * 40
INVENTORY = {"nodes": [{"node": "gway-001", "registered": True,
                        "identity_verified": True, "reachable": "reachable"}]}


class BrokerTests(unittest.TestCase):
    def test_attestation_and_allowlist(self):
        approved = authorize_deploy("arthexis/ocpp-reports", "gway-001", "main",
                                    inventory=INVENTORY, resolve_sha=lambda *_: SHA)
        self.assertEqual(approved["sha"], SHA)
        with self.assertRaises(PermissionError):
            authorize_deploy("arthexis/ocpp-csms", "gway-001", "main",
                             inventory=INVENTORY, resolve_sha=lambda *_: SHA)
        with self.assertRaises(PermissionError):
            authorize_deploy("arthexis/ocpp-reports", "gway-001", "main",
                             inventory={"nodes": []}, resolve_sha=lambda *_: SHA)

    def test_sha_mismatch_fails_closed(self):
        with self.assertRaises(ValueError):
            authorize_deploy("arthexis/ocpp-reports", "gway-001", "b" * 40,
                             inventory=INVENTORY, resolve_sha=lambda *_: SHA)

    def test_durable_dedup_and_principal_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)
            path = Path(directory) / "receipts.sqlite3"
            ledger = DeploymentReceipts(path)
            approved = authorize_deploy("arthexis/ocpp-reports", "gway-001", "main",
                                        inventory=INVENTORY, resolve_sha=lambda *_: SHA)
            request_id = "a" * 32
            self.assertEqual(ledger.reserve(request_id, "operator", approved)["state"], "reserved")
            self.assertTrue(ledger.transition(request_id, "reserved", "running"))
            self.assertFalse(ledger.transition(request_id, "reserved", "running"))
            self.assertEqual(DeploymentReceipts(path).reserve(request_id, "operator", approved)["state"], "running")
            with self.assertRaises(PermissionError):
                ledger.reserve(request_id, "other", approved)
            with self.assertRaises(PermissionError):
                ledger.status(request_id, "other")
            self.assertTrue(ledger.transition(request_id, "running", "succeeded"))
            self.assertFalse(ledger.transition(request_id, "succeeded", "running"))


if __name__ == "__main__":
    unittest.main()
