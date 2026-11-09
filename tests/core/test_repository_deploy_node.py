"""Offline node deployment ledger tests: no SSH or installer execution."""
import json
import hashlib
import stat
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.repository_deploy_node import NodeDeploymentLedger, publish_installed_receipt

SHA = "a" * 40
RID = "b" * 32


class NodeLedgerTests(unittest.TestCase):
    def test_atomic_receipt_and_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            receipt = Path(tmp) / "installed.json"
            manifest.write_text('{"release":"verified"}')
            actual_lstat = Path.lstat
            def trusted_lstat(path):
                info = actual_lstat(path)
                return type("Info", (), {"st_mode": info.st_mode,
                                        "st_uid": 0})()
            with patch("gway_remote.repository_deploy_node.Path.lstat", trusted_lstat):
                row = publish_installed_receipt(
                    receipt, repository="arthexis/odoo-gelectriic",
                    node="gway-001", sha=SHA, manifest_path=manifest)
            self.assertEqual(row["manifest_sha256"],
                             hashlib.sha256(manifest.read_bytes()).hexdigest())
            self.assertEqual(json.loads(receipt.read_text()), row)
            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
            self.assertFalse(list(Path(tmp).glob(".installed-*")))

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
