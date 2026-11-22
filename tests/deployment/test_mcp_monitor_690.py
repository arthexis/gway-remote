"""Out-of-process health sampling reports fixed classes and restart bursts."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[2] / "scripts/mcp-health-monitor.py"
spec = importlib.util.spec_from_file_location("mcp_monitor_690", path)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class MonitorTests(unittest.TestCase):
    def test_healthy_sample_does_not_claim_authenticated_acceptance(self):
        result = monitor.sample({"gateway_restart_count": 2},
            reader=lambda _: {"active": True, "restart_count": 2, "exit_status": 0},
            probe=lambda *_: True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["authenticated_external"], "not_checked")
        self.assertEqual(result["restart_increase"], 0)

    def test_gateway_down_and_restart_burst_are_reported_separately(self):
        result = monitor.sample({"gateway_restart_count": 2},
            reader=lambda unit: {"active": unit != monitor.UNITS[0], "restart_count": 8, "exit_status": 1},
            probe=lambda url, _: "19010" not in url)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(set(result["failures"]),
                         {"service_unavailable", "gateway_unavailable", "restart_backoff"})
        self.assertEqual(result["oauth_http"], "ok")

    def test_first_sample_does_not_invent_restart_rate(self):
        result = monitor.sample(reader=lambda _: {"active": True, "restart_count": 1195, "exit_status": 0},
                                probe=lambda *_: True)
        self.assertIsNone(result["restart_increase"])
        self.assertEqual(result["status"], "ok")
