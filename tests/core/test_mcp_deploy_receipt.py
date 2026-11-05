"""Deployment receipts survive oneshot unit garbage collection and expose failures."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/gway-remote-deploy-receipt.py"

class DeploymentReceiptTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("gway_deploy_receipt", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module.STATE = Path(self.tmp.name)
        self.module.RECEIPT = self.module.STATE / "status.json"

    def read(self):
        return json.loads(self.module.RECEIPT.read_text())

    def test_success_is_durable_and_tracks_invocation(self):
        with patch("sys.argv", ["receipt", "begin"]):
            self.assertEqual(self.module.main(), 0)
        before = self.read()
        self.assertEqual(before["state"], "running")
        self.assertEqual(len(before["attempt_id"]), 32)
        with patch("sys.argv", ["receipt", "finish"]), patch.dict(
                os.environ, {"SERVICE_RESULT": "success", "EXIT_STATUS": "0"}):
            self.assertEqual(self.module.main(), 0)
        after = self.read()
        self.assertEqual(after["state"], "succeeded")
        self.assertEqual(after["attempt_id"], before["attempt_id"])
        self.assertEqual(after["exit_status"], "0")
        self.assertIsNotNone(after["finished_at"])

    def test_failed_service_is_not_reported_successful(self):
        with patch("sys.argv", ["receipt", "begin"]):
            self.module.main()
        with patch("sys.argv", ["receipt", "finish"]), patch.dict(
                os.environ, {"SERVICE_RESULT": "exit-code", "EXIT_STATUS": "2"}):
            self.module.main()
        self.assertEqual(self.read()["state"], "failed")
        self.assertEqual(self.read()["exit_status"], "2")

    def test_missing_prestart_remains_failure(self):
        with patch("sys.argv", ["receipt", "finish"]), patch.dict(
                os.environ, {"SERVICE_RESULT": "resources", "EXIT_STATUS": "unknown"}):
            self.module.main()
        self.assertEqual(self.read()["state"], "failed")

    def test_odoo_receipt_is_separate_from_existing_deployment(self):
        with patch("sys.argv", ["receipt", "begin"]):
            self.module.main()
        old = self.read()
        with patch("sys.argv", ["receipt", "begin", "odoo-gelectriic"]):
            self.assertEqual(self.module.main(), 0)
        specific = self.module.STATE / "status-odoo-gelectriic.json"
        assert specific.is_file()
        self.assertEqual(json.loads(specific.read_text())["application"],
                         "odoo-gelectriic")
        self.assertEqual(self.read()["attempt_id"], old["attempt_id"])
        with patch("sys.argv", ["receipt", "finish", "odoo-gelectriic"]), patch.dict(
                os.environ, {"SERVICE_RESULT": "success", "EXIT_STATUS": "0"}):
            self.assertEqual(self.module.main(), 0)
        self.assertEqual(json.loads(specific.read_text())["state"], "succeeded")
        self.assertEqual(self.read()["state"], "running")

    def test_unknown_application_refused(self):
        with patch("sys.argv", ["receipt", "begin", "../unexpected"]):
            self.assertEqual(self.module.main(), 2)

    def test_symlink_receipt_refused(self):
        target = self.module.STATE / "other"
        target.write_text("test")
        self.module.RECEIPT.symlink_to(target)
        with patch("sys.argv", ["receipt", "begin"]):
            with self.assertRaises(RuntimeError):
                self.module.main()

if __name__ == "__main__":
    unittest.main()
