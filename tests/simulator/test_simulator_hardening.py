import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote import simulator_runner as runner


class SimulatorHardeningTests(unittest.TestCase):
    def test_zombie_is_not_alive(self):
        with patch.object(runner, "_identity", return_value=None):
            self.assertFalse(runner._alive({"pid": 123, "identity": "77"}))

    def test_pid_reuse_is_not_alive(self):
        with patch.object(runner, "_identity", return_value="99"):
            self.assertFalse(runner._alive({"pid": 123, "identity": "77"}))

    def test_stop_is_idempotent_when_already_stopping(self):
        with tempfile.TemporaryDirectory() as root, patch.object(
                runner, "STATE_DIR", Path(root)), patch.object(
                runner, "_identity", return_value="77"), patch(
                "os.kill") as kill:
            runner._lock().close()
            (Path(root) / "run.json").write_text(
                '{"pid":123,"identity":"77","scenario":"boot","target":"192.168.1.2:9000","stopping":true}')
            self.assertEqual(runner.stop({})["state"], "stopping")
            self.assertEqual(runner.stop({})["state"], "stopping")
            kill.assert_not_called()

    def test_nonfinite_parameters_rejected(self):
        with patch.object(runner, "_networks", return_value=([], [
                __import__("ipaddress").ip_network("192.168.50.0/24")])):
            with self.assertRaises(ValueError):
                runner.start({"host": "192.168.50.2", "scenario": "remote", "power": float("nan")})
