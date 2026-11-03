"""Optional RTC/ambient observations are read-only and nonfatal."""
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from gway_remote.hardware_diagnostics import inspect, format_hardware


class HardwareDiagnosticTests(TestCase):
    def test_missing_sensors_are_unavailable_not_unhealthy(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            result = inspect(rtc_root=base / "rtc", i2c_root=base / "i2c")
        self.assertEqual(result["rtc"], {"status": "unavailable", "devices": []})
        self.assertEqual(result["ambient_temperature"]["status"], "unavailable")
        self.assertIn("unavailable", format_hardware(result))

    def test_ds3231_temperature_and_hardware_clock(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            rtc = base / "rtc/rtc0"
            rtc.mkdir(parents=True)
            (rtc / "name").write_text("rtc-ds3232")
            (rtc / "date").write_text("2026-11-03")
            (rtc / "time").write_text("05:04:03")
            (rtc / "hctosys").write_text("1")
            hwmon = base / "i2c/1-0068/hwmon/hwmon3"
            hwmon.mkdir(parents=True)
            (hwmon / "temp1_input").write_text("33750")
            result = inspect(rtc_root=base / "rtc", i2c_root=base / "i2c")
        self.assertEqual(result["rtc"]["status"], "available")
        self.assertEqual(result["rtc"]["devices"][0]["time_utc"], "2026-11-03T05:04:03+00:00")
        self.assertTrue(result["rtc"]["devices"][0]["initialized_system_clock"])
        self.assertEqual(result["ambient_temperature"]["celsius"], 33.75)

    def test_invalid_or_missing_readings_never_crash(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            rtc = base / "rtc/rtc0"
            rtc.mkdir(parents=True)
            (rtc / "date").write_text("bad date")
            (rtc / "time").write_text("bad time")
            hwmon = base / "i2c/1-0068/hwmon/hwmon0"
            hwmon.mkdir(parents=True)
            (hwmon / "temp1_input").write_text("nan")
            result = inspect(rtc_root=base / "rtc", i2c_root=base / "i2c")
        self.assertIsNone(result["rtc"]["devices"][0]["time_utc"])
        self.assertEqual(result["ambient_temperature"]["status"], "unavailable")

    def test_never_invokes_hwclock_or_other_subprocess(self):
        with tempfile.TemporaryDirectory() as root, patch("subprocess.run", side_effect=AssertionError("unexpected command")):
            base = Path(root)
            result = inspect(rtc_root=base / "rtc", i2c_root=base / "i2c")
            self.assertEqual(result["rtc"]["status"], "unavailable")
