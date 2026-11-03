"""Watchdog inspection and explicit configuration contracts."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.watchdog import inspect, configure, format_watchdog, HEADER
from gway_remote.status import status, format_status


def finished(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout, "")


class WatchdogTests(unittest.TestCase):
    def test_missing_watchdog_and_systemctl_remains_optional(self):
        with tempfile.TemporaryDirectory() as folder:
            report = inspect(root=Path(folder) / "absent",
                             runner=lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["devices"], [])
        self.assertIsNone(report["runtime_watchdog_usec"])
        self.assertIn("Watchdog: unavailable", format_watchdog(report))

    def test_report_inactive_and_systemd_runtime_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            dev = Path(folder) / "watchdog0"
            dev.mkdir()
            (dev / "identity").write_text("Broadcom BCM2835 Watchdog timer")
            (dev / "state").write_text("inactive")
            (dev / "timeout").write_text("15")
            (dev / "timeleft").write_text("0")
            report = inspect(root=Path(folder), runner=lambda *a, **k: finished(
                "RuntimeWatchdogUSec=0\nRebootWatchdogUSec=10min\n"))
        self.assertEqual(report["status"], "available")
        self.assertEqual(report["devices"][0]["state"], "inactive")
        self.assertEqual(report["devices"][0]["timeout_seconds"], 15)
        self.assertEqual(report["runtime_watchdog_usec"], "0")
        self.assertEqual(report["reboot_watchdog_usec"], "10min")

    def test_requires_apply_and_root_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "watchdog.conf"
            with self.assertRaisesRegex(ValueError, "apply"):
                configure("disable", path=path, geteuid=lambda: 0)
            with self.assertRaises(PermissionError):
                configure("disable", apply=True, path=path, geteuid=lambda: 1000)
            self.assertFalse(path.exists())

    def test_enable_requires_watchdog_and_accepted_timeout(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "watchdog.conf"
            with self.assertRaises(ValueError):
                configure("enable", seconds=999, apply=True, path=path, geteuid=lambda: 0)
            with self.assertRaisesRegex(RuntimeError, "no watchdog"):
                configure("enable", seconds=30, apply=True,
                          path=path, root=Path(folder) / "none",
                          runner=lambda *a, **k: finished(), geteuid=lambda: 0)
            self.assertFalse(path.exists())

    def test_enable_then_disable_writes_owned_dropin_and_reexec_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "watchdogs"
            (root / "watchdog0").mkdir(parents=True)
            path = Path(folder) / "system.conf.d" / "watchdog.conf"
            commands = []
            def runner(argv, **kwargs):
                commands.append(argv)
                return finished("RuntimeWatchdogUSec=30s\nRebootWatchdogUSec=10min\n"
                                if argv[1] == "show" else "")
            result = configure("enable", seconds=30, apply=True, path=path,
                               root=root, runner=runner, geteuid=lambda: 0)
            self.assertEqual(result["action"], "enable")
            self.assertIn("RuntimeWatchdogSec=30s", path.read_text())
            self.assertEqual(commands.count(["systemctl", "daemon-reexec"]), 1)
            result = configure("disable", apply=True, path=path,
                               root=root, runner=runner, geteuid=lambda: 0)
            self.assertEqual(result["configured_timeout_seconds"], 0)
            self.assertIn("RuntimeWatchdogSec=0\n", path.read_text())
            self.assertEqual(commands.count(["systemctl", "daemon-reexec"]), 2)
            self.assertTrue(all(argv[0] == "systemctl" for argv in commands))

    def test_refuses_unowned_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "watchdog.conf"
            path.write_text("[Manager]\nRuntimeWatchdogSec=0\n")
            with self.assertRaisesRegex(RuntimeError, "not owned"):
                configure("disable", apply=True, path=path, geteuid=lambda: 0)
            self.assertEqual(path.read_text(), "[Manager]\nRuntimeWatchdogSec=0\n")

    def test_rolls_back_after_reexec_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "watchdog.conf"
            path.write_text(HEADER + "[Manager]\nRuntimeWatchdogSec=30s\n")
            calls = []
            def runner(argv, **kwargs):
                calls.append(argv)
                return finished("", 1 if len(calls) == 1 else 0)
            with self.assertRaisesRegex(RuntimeError, "daemon-reexec failed"):
                configure("disable", apply=True, path=path, runner=runner,
                          geteuid=lambda: 0)
            self.assertIn("RuntimeWatchdogSec=30s", path.read_text())
            self.assertEqual(len(calls), 2)

    def test_status_includes_watchdog_without_changing_health(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("gway_remote.status.watchdog_inspect",
                       return_value={"status": "unavailable", "devices": [],
                                     "runtime_watchdog_usec": "0",
                                     "reboot_watchdog_usec": "10min"}):
                with patch("gway_remote.status.installed_revision", return_value=None):
                    report = status(Path(folder), probe=lambda _: True)
        self.assertEqual(report["watchdog"]["status"], "unavailable")
        self.assertIn("Watchdog: unavailable", format_status(report))
        self.assertTrue(all(x["health"] == "healthy" for x in report["components"]
                            if x["name"] != "gway-bastion"))


if __name__ == "__main__":
    unittest.main()
