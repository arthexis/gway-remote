import unittest
from unittest.mock import patch

from gway_remote import simulator_runner


class SimulatorOutcomeTests(unittest.TestCase):
    def test_unknown_outcome(self):
        record = {"pid": 100, "identity": "abc", "scenario": "boot", "target": "localhost"}
        with patch.object(simulator_runner, "_read", return_value=record), patch.object(
            simulator_runner, "_alive", return_value=False
        ):
            self.assertEqual(simulator_runner._status()["outcome"], "unknown")

    def test_monitor_exit_record(self):
        import json
        import tempfile
        from pathlib import Path
        record = {"pid": 100, "identity": "abc", "run_id": "test123",
                  "scenario": "boot", "target": "localhost"}
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "exit-test123.json").write_text(json.dumps({"exit_code": 0}))
            with patch.object(simulator_runner, "STATE_DIR", Path(directory)), patch.object(
                simulator_runner, "_read", return_value=record
            ), patch.object(simulator_runner, "_alive", return_value=False):
                self.assertEqual(simulator_runner._status()["outcome"], "completed")

    def test_recorded_failure(self):
        record = {"pid": 100, "identity": "abc", "scenario": "boot",
                  "target": "localhost", "exit_code": 2}
        with patch.object(simulator_runner, "_read", return_value=record), patch.object(
            simulator_runner, "_alive", return_value=False
        ):
            self.assertEqual(simulator_runner._status()["outcome"], "failed")
            self.assertEqual(simulator_runner._status()["exit_code"], 2)
