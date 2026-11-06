"""Network snapshot contract, including absent and degraded interfaces."""
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import subprocess

from gway_remote.network_diagnostics import _ipv4_addresses, inspect, format_network


class NetworkTests(TestCase):
    def test_all_three_interfaces_and_missing_wlan1(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, state, flags in (("eth0", "up", "0x1003"), ("wlan0", "down", "0x1002")):
                path = root / name
                path.mkdir()
                (path / "operstate").write_text(state)
                (path / "flags").write_text(flags)
                (path / "address").write_text("02:00:00:00:00:01")
            report = inspect(sys_net=root, addresses={
                "eth0": ["192.0.2.1", "192.0.2.2"], "wlan0": []})
        self.assertEqual(report["schema"], "gway-remote/network/v1")
        self.assertEqual(list(report["interfaces"]), ["eth0", "wlan0", "wlan1"])
        self.assertEqual(report["interfaces"]["eth0"]["ipv4"], ["192.0.2.1", "192.0.2.2"])
        self.assertTrue(report["interfaces"]["eth0"]["up"])
        self.assertFalse(report["interfaces"]["wlan0"]["up"])
        self.assertTrue(report["interfaces"]["wlan0"]["present"])
        self.assertFalse(report["interfaces"]["wlan1"]["present"])
        self.assertEqual(report["interfaces"]["wlan1"]["ipv4"], [])
        self.assertIn("wlan1: absent", format_network(report))

    def test_ip_json_rejects_bad_data_and_deduplicates(self):
        output = json.dumps([
            {"ifname": "eth0", "addr_info": [
                {"family": "inet", "local": "192.0.2.10"},
                {"family": "inet", "local": "192.0.2.10"},
                {"family": "inet", "local": "invalid"},
                {"family": "inet6", "local": "::1"}]},
            {"ifname": "wg0", "addr_info": [{"family": "inet", "local": "10.0.0.1"}]}
        ])
        with patch("gway_remote.network_diagnostics.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout=output, stderr="")
            self.assertEqual(_ipv4_addresses(), {"eth0": ["192.0.2.10"]})
            run.return_value = subprocess.CompletedProcess([], 0, stdout="invalid", stderr="")
            self.assertEqual(_ipv4_addresses(), {})
            run.side_effect = subprocess.TimeoutExpired("ip", 3)
            self.assertEqual(_ipv4_addresses(), {})

    def test_missing_tools_and_sysfs_are_nonfatal(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("gway_remote.network_diagnostics.subprocess.run", side_effect=FileNotFoundError()):
                report = inspect(sys_net=Path(directory))
        self.assertTrue(all(not item["present"] for item in report["interfaces"].values()))
        self.assertTrue(all(not item["ipv4"] for item in report["interfaces"].values()))
