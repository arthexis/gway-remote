import tempfile
import ipaddress
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote import simulator_runner as runner
from gway_remote import mobile


class SimulatorRunnerTests(unittest.TestCase):
    def test_idle_status_and_results(self):
        with tempfile.TemporaryDirectory() as root, patch.object(runner, "STATE_DIR", Path(root)):
            self.assertEqual(mobile.execute("simulator-status", {})["state"], "idle")
            self.assertEqual(mobile.execute("simulator-results", {})["output"], "")
            self.assertEqual(mobile.execute("simulator-stop", {})["state"], "idle")

    def test_rejects_off_link_and_unapproved_parameters(self):
        with patch.object(runner, "_networks", return_value=([], [
                ipaddress.ip_network("192.168.50.0/24")])):
            for args in (
                {"host": "8.8.8.8"},
                {"host": "192.168.50.2", "scenario": "bad"},
                {"host": "192.168.50.2", "scenario": "boot", "rfid": "ABC"},
                {"host": "192.168.50.2", "scenario": "charge", "duration": True},
                {"host": "192.168.50.2", "scenario": "charge", "connector": 0},
            ):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    runner.start(args)

    def test_permitted_target_allows_only_ipv4_loopback_or_wired_peers(self):
        with patch.object(runner, "_networks", return_value=([], [
                ipaddress.ip_network("192.168.50.0/24")])):
            self.assertTrue(runner._permitted_target("127.0.0.1"))
            self.assertTrue(runner._permitted_target("127.0.0.42"))
            self.assertTrue(runner._permitted_target("192.168.50.2"))
            self.assertFalse(runner._permitted_target("8.8.8.8"))
            self.assertFalse(runner._permitted_target("::1"))

    def test_catalog_has_lifecycle_operations(self):
        names = {entry["name"] for entry in mobile.commands()}
        self.assertTrue({"simulator-start", "simulator-stop", "simulator-status",
                         "simulator-results"} <= names)
