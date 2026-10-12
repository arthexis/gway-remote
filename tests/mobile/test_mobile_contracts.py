"""Regression contracts for the future mobile read-only adapter.

These tests exercise existing operation functions directly; no HTTP layer exists yet.
"""
import json
import tempfile
import unittest
from pathlib import Path

from gway_remote.csms_health import csms_probe
from gway_remote.status import status, format_status


class MobileReadOnlyContracts(unittest.TestCase):
    def test_probe_result_is_json_serializable_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "ocpp-csms"
            executable.touch()
            data = root / "data"
            data.mkdir()
            commands = []
            document = {
                "schema": "ocpp-csms/status/v1",
                "data": {
                    "server": {"state": "running"},
                    "storage": {"database": "ok", "transactions": "ok"},
                },
            }

            def runner(argv):
                commands.append(argv)
                if argv[:2] == ["systemctl", "is-active"]:
                    return "active"
                return json.dumps(document)

            result = csms_probe(runner=runner, executable=executable, data_dir=data)
            self.assertTrue(result["healthy"])
            self.assertEqual(json.loads(json.dumps(result)), result)
            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[0], ["systemctl", "is-active", "ocpp-csms.service"])
            self.assertEqual(commands[1][-2:], ["status", "--json"])

    def test_status_contract_is_structured_and_formatting_does_not_mutate(self):
        with tempfile.TemporaryDirectory() as directory:
            result = status(Path(directory), probe=lambda _: True)
            snapshot = json.loads(json.dumps(result))
            self.assertEqual(result["schema"], "gway-remote/status/v1")
            self.assertIn("checked_at", result)
            self.assertIn("node", result)
            self.assertTrue(result["components"])
            self.assertIn("Component", format_status(result))
            self.assertEqual(result, snapshot)

    def test_status_probe_failure_stays_serializable(self):
        def unavailable(_):
            raise OSError("offline")

        with tempfile.TemporaryDirectory() as directory:
            result = status(Path(directory), probe=unavailable)
            self.assertTrue(all(c["health"] == "unknown" for c in result["components"]))
            json.dumps(result)


if __name__ == "__main__":
    unittest.main()
