"""CSMS health checks are read-only, strict, and independent of charger sessions."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.csms_health import csms_health, csms_probe


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.exe = self.root / "ocpp-csms"
        self.exe.touch()
        self.data = self.root / "data"
        self.data.mkdir()
        self.commands = []
        self.document = {
            "schema": "ocpp-csms/status/v1",
            "data": {
                "server": {"state": "running"},
                "storage": {"database": "ok", "transactions": "ok"},
                "chargers": [{"connected": True, "connectors": [
                    {"status": "Charging", "transaction": {"id": 17}}
                ]}],
            },
        }

    def runner(self, argv):
        self.commands.append(argv)
        if argv[:2] == ["systemctl", "is-active"]:
            return "active"
        return json.dumps(self.document)

    def check(self):
        return csms_health(runner=self.runner, executable=self.exe, data_dir=self.data)

    def test_discovers_cli_on_path(self):
        with patch("gway_remote.csms_health.shutil.which", return_value=str(self.exe)):
            result = csms_probe(runner=self.runner, data_dir=self.data)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["executable"], str(self.exe))

    def test_default_uses_active_storage_selected_by_csms(self):
        # No override: the CLI resolves the active schema directory itself.
        with patch("pathlib.Path.home", return_value=self.root):
            result = csms_probe(runner=self.runner, executable=self.exe)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["data_dir"], "auto")
        self.assertEqual(self.commands, [
            ["systemctl", "is-active", "ocpp-csms.service"],
            [str(self.exe), "status", "--json"],
        ])

    def test_explicit_storage_override_is_forwarded(self):
        result = csms_probe(runner=self.runner, executable=self.exe, data_dir=self.data)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["data_dir"], str(self.data))
        self.assertEqual(self.commands[-1], [
            str(self.exe), "--data-dir", str(self.data), "status", "--json",
        ])

    def test_default_does_not_require_legacy_parent_directory(self):
        # Only the CLI can determine whether its active schema storage is healthy.
        with patch("pathlib.Path.home", return_value=self.root):
            result = csms_probe(runner=self.runner, executable=self.exe)
        self.assertTrue(result["healthy"])

    def test_explicit_missing_storage_rejected_before_invoking_cli(self):
        missing = self.root / "missing"
        result = csms_probe(runner=self.runner, executable=self.exe, data_dir=missing)
        self.assertFalse(result["healthy"])
        self.assertEqual(result["reason"], "data directory missing")
        self.assertEqual(self.commands, [])

    def test_healthy_even_during_active_charge(self):
        self.assertTrue(self.check())
        self.assertEqual(self.commands[0], ["systemctl", "is-active", "ocpp-csms.service"])
        self.assertEqual(self.commands[1][-2:], ["status", "--json"])
        self.assertFalse(any("restart" in cmd or "start" in cmd for cmd in self.commands))

    def test_probe_explains_stopped_service(self):
        result = csms_probe(runner=lambda _: "inactive", executable=self.exe, data_dir=self.data)
        self.assertFalse(result["healthy"])
        self.assertIn("service", result["reason"])

    def test_stopped_service_fails(self):
        self.assertFalse(csms_health(runner=lambda _: "inactive",
                                     executable=self.exe, data_dir=self.data))

    def test_missing_storage_fails(self):
        self.data.rmdir()
        self.assertFalse(self.check())

    def test_malformed_contract_fails(self):
        self.document["schema"] = "other"
        self.assertFalse(self.check())

    def test_missing_database_fails(self):
        self.document["data"]["storage"]["database"] = "missing"
        self.assertFalse(self.check())

    def test_server_stopped_fails(self):
        self.document["data"]["server"]["state"] = "stopped"
        self.assertFalse(self.check())


if __name__ == "__main__":
    unittest.main()
