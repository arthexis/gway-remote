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

    def test_host_resources_are_reported_without_external_tools(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base / "meminfo").write_text(
                "MemTotal:        4000000 kB\nMemAvailable:    1000000 kB\n")
            (base / "uptime").write_text("3600.25 1234.0\n")
            zone = base / "thermal/thermal_zone0"
            zone.mkdir(parents=True)
            (zone / "temp").write_text("54125")
            (base / "freq").write_text("1500000")
            (base / "model").write_text("Raspberry Pi 4 Model B\x00")
            with patch("gway_remote.hardware_diagnostics.shutil.disk_usage") as disk:
                disk.return_value = type("Usage", (), {
                    "total": 1000, "free": 400})()
                result = inspect(
                    rtc_root=base / "rtc", i2c_root=base / "i2c",
                    meminfo=base / "meminfo", uptime=base / "uptime",
                    thermal_root=base / "thermal", cpu_freq=base / "freq",
                    model=base / "model", disk_root=base)
        host = result["host"]
        self.assertEqual(host["cpu_temperature_c"], 54.125)
        self.assertEqual(host["cpu_frequency_mhz"], 1500.0)
        self.assertEqual(host["memory"]["total_bytes"], 4096000000)
        self.assertEqual(host["memory"]["used_percent"], 75.0)
        self.assertEqual(host["uptime_seconds"], 3600.2)
        self.assertEqual(host["root_filesystem"]["used_percent"], 60.0)

    def test_missing_host_metrics_are_nullable(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            with patch("gway_remote.hardware_diagnostics.shutil.disk_usage",
                       side_effect=OSError("unmounted")):
                result = inspect(
                    rtc_root=base / "rtc", i2c_root=base / "i2c",
                    meminfo=base / "missing", uptime=base / "missing",
                    thermal_root=base / "missing", cpu_freq=base / "missing",
                    model=base / "missing", disk_root=base / "missing")
        host = result["host"]
        self.assertIsNone(host["memory"]["total_bytes"])
        self.assertIsNone(host["cpu_temperature_c"])
        self.assertIsNone(host["uptime_seconds"])
        self.assertIsNone(host["root_filesystem"]["total_bytes"])
        self.assertIn("RAM:", format_hardware(result))

    def test_never_invokes_hwclock_or_other_subprocess(self):
        with tempfile.TemporaryDirectory() as root, patch("subprocess.run", side_effect=AssertionError("unexpected command")):
            base = Path(root)
            result = inspect(rtc_root=base / "rtc", i2c_root=base / "i2c")
            self.assertEqual(result["rtc"]["status"], "unavailable")
