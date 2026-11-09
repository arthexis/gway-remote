"""Offline node deployment ledger tests: no SSH or installer execution."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.repository_deploy_node import NodeDeploymentLedger

SHA = "a" * 40
RID = "b" * 32


class NodeLedgerTests(unittest.TestCase):
    def test_idempotent_reservation_and_no_rebinding(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o700)
            ledger = NodeDeploymentLedger(Path(tmp) / "jobs.sqlite3")
            with patch("gway_remote.repository_deploy_node.repository_installer_argv",
                       return_value=["/fixed", SHA]):
                kwargs = dict(request_id=RID, principal="authenticated-principal",
                              node="gway-001", repository="arthexis/odoo-gelectriic", sha=SHA)
                self.assertTrue(ledger.reserve(**kwargs)["new"])
                self.assertFalse(ledger.reserve(**kwargs)["new"])
                with self.assertRaises(PermissionError):
                    ledger.reserve(**{**kwargs, "principal": "other"})
                with self.assertRaises(PermissionError):
                    ledger.reserve(**{**kwargs, "sha": "c" * 40})
                self.assertTrue(ledger.transition(RID, "authenticated-principal",
                                                  "reserved", "running"))
                self.assertFalse(ledger.transition(RID, "authenticated-principal",
                                                   "reserved", "running"))
                self.assertTrue(ledger.transition(RID, "authenticated-principal",
                                                  "running", "unknown"))
                self.assertFalse(ledger.transition(RID, "authenticated-principal",
                                                   "running", "succeeded"))
                self.assertEqual(ledger.reserve(**kwargs)["state"], "unknown")

    def test_unsafe_directory_and_missing_registration_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o777)
            with self.assertRaises(PermissionError):
                NodeDeploymentLedger(Path(tmp) / "jobs.sqlite3")
            os.chmod(tmp, 0o700)
            ledger = NodeDeploymentLedger(Path(tmp) / "jobs.sqlite3")
            with patch("gway_remote.repository_deploy_node.repository_installer_argv",
                       side_effect=PermissionError("not installed")):
                with self.assertRaises(PermissionError):
                    ledger.reserve(request_id=RID, principal="p", node="gway-001",
                                   repository="arthexis/odoo-gelectriic", sha=SHA)


if __name__ == "__main__":
    unittest.main()
