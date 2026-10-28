import tempfile
import unittest
import json
from subprocess import CompletedProcess
from pathlib import Path
from unittest.mock import patch

from gway_remote.health import component_health


class HealthTests(unittest.TestCase):
    def test_csms_never_claims_health_without_service_probe(self):
        with patch("gway_remote.health.csms_health", return_value=False) as probe:
            self.assertFalse(component_health("ocpp-csms"))
            probe.assert_called_once_with()

    def test_unknown_target_fails_closed(self):
        self.assertFalse(component_health("unknown"))

    def test_reports_status_requires_ready_json(self):
        from gway_remote.health import _reports_ready
        exe = Path("/fake/ocpp-reports")
        for status in ("unconfigured", "degraded", "invalid", None):
            payload = {"state": status, "config": {"state": "valid"},
                       "warehouse": {"state": "ready"}}
            with self.subTest(status=status):
                with patch("gway_remote.health.subprocess.run",
                           return_value=CompletedProcess([], 0, json.dumps(payload), "")):
                    self.assertFalse(_reports_ready(exe))
        for payload in ("", "not json", "[]", '{"state":"ready"}'):
            with self.subTest(payload=payload):
                with patch("gway_remote.health.subprocess.run",
                           return_value=CompletedProcess([], 0, payload, "")):
                    self.assertFalse(_reports_ready(exe))
        healthy = {"state": "ready", "config": {"state": "valid"},
                   "warehouse": {"state": "ready"}}
        with patch("gway_remote.health.subprocess.run",
                   return_value=CompletedProcess([], 0, json.dumps(healthy), "")) as runner:
            self.assertTrue(_reports_ready(exe))
            runner.assert_called_once()
            self.assertEqual(runner.call_args.args[0][-2:], ["status", "--json"])

    def test_reports_nonzero_exit_never_healthy(self):
        from gway_remote.health import _reports_ready
        payload = '{"state":"ready","config":{"state":"valid"},"warehouse":{"state":"ready"}}'
        with patch("gway_remote.health.subprocess.run",
                   return_value=CompletedProcess([], 2, payload, "")):
            self.assertFalse(_reports_ready(Path("/fake/reports")))

    def test_missing_executable_fails_simulator(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("pathlib.Path.home", return_value=Path(directory)):
                self.assertFalse(component_health("ocpp-simulator"))


if __name__ == "__main__":
    unittest.main()
