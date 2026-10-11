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

    def test_recorded_failure(self):
        record = {"pid": 100, "identity": "abc", "scenario": "boot",
                  "target": "localhost", "exit_code": 2}
        with patch.object(simulator_runner, "_read", return_value=record), patch.object(
            simulator_runner, "_alive", return_value=False
        ):
            self.assertEqual(simulator_runner._status()["outcome"], "failed")
            self.assertEqual(simulator_runner._status()["exit_code"], 2)
