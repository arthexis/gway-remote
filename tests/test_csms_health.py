"""CSMS health checks are read-only, strict, and independent of charger sessions."""
import json
import tempfile
import unittest
from pathlib import Path

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
