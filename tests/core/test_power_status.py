"""Optional voltage probe preserves status on all platforms."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.power_status import probe, format_power
from gway_remote.status import status, format_status


def process(output, returncode=0):
    return subprocess.CompletedProcess(["vcgencmd", "get_throttled"], returncode, output, "")


class VoltageStatusTests(unittest.TestCase):
    def test_clean_power(self):
        result = probe(runner=lambda *a, **k: process("throttled=0x0\\n"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["raw"], "0x0")
        self.assertFalse(result["undervoltage_now"])
        self.assertFalse(result["undervoltage_occurred"])

    def test_current_and_historical_power_flags(self):
        result = probe(runner=lambda *a, **k: process("throttled=0x50005\\n"))
        self.assertEqual(result["status"], "warning")
        self.assertTrue(result["undervoltage_now"])
        self.assertTrue(result["throttled_now"])
        self.assertTrue(result["undervoltage_occurred"])
        self.assertTrue(result["throttled_occurred"])
        self.assertIn("since_boot=", format_power(result))

    def test_history_only_flags_still_report_warning(self):
        result = probe(runner=lambda *a, **k: process("throttled=0x10000"))
        self.assertFalse(result["undervoltage_now"])
        self.assertTrue(result["undervoltage_occurred"])
        self.assertEqual(result["status"], "warning")

    def test_missing_timeout_nonzero_or_malformed_are_unavailable(self):
        runners = [
            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()),
            lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("vcgencmd", 2)),
            lambda *a, **k: process("", 1),
            lambda *a, **k: process("throttled=not-a-number"),
        ]
        for runner in runners:
            with self.subTest(runner=runner):
                result = probe(runner=runner)
                self.assertEqual(result["status"], "unavailable")
                self.assertIsNone(result["undervoltage_now"])

    def test_status_preserves_component_health_when_power_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("gway_remote.status.power_probe", return_value=probe(
                runner=lambda *a, **k: process("", 1))):
                with patch("gway_remote.status.installed_revision", return_value=None):
                    report = status(Path(folder), probe=lambda _: True)
        self.assertEqual(report["power"]["status"], "unavailable")
        self.assertTrue(all(item["health"] == "healthy"
                            for item in report["components"]
                            if item["name"] != "gway-bastion"))
        self.assertIn("Power: unavailable", format_status(report))

    def test_status_includes_power_flags_in_json_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("gway_remote.status.power_probe",
                       return_value=probe(runner=lambda *a, **k: process("throttled=0x10000"))):
                with patch("gway_remote.status.installed_revision", return_value=None):
                    report = status(Path(folder), probe=lambda _: True)
        self.assertTrue(report["power"]["undervoltage_occurred"])
        self.assertIn("Power: warning", format_status(report))


if __name__ == "__main__":
    unittest.main()
