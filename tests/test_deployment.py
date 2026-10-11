"""Behavioral tests: no real services, network requests or privileged writes."""
import pathlib
import socket
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.deployment import deploy, health, SERVICE


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.executable = self.root / "gway-remote"
        self.executable.write_text("old")
        self.executable.chmod(0o750)
        self.sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.sock.close)
        self.sock.bind(str(self.root / "bus"))
        self.commands = []
        self.calls = []
        self.fail_restart = False
        self.fail_probe = False

    def execute(self, *args):
        self.commands.append(args)
        if args[:3] == ("sudo", "-n", "cp"):
            pathlib.Path(args[-1]).write_bytes(pathlib.Path(args[-2]).read_bytes())
        if args[:3] == ("sudo", "-n", "install"):
            self.executable.write_bytes(pathlib.Path(args[-2]).read_bytes())
            self.executable.chmod(int(args[4], 8))
        if args[:3] == ("systemctl", "--user", "restart") and self.fail_restart:
            self.fail_restart = False
            raise RuntimeError("restart failed")

    def install(self):
        self.calls.append("install")
        self.executable.write_text("new")

    def probe(self, token):
        self.calls.append("health")
        if self.fail_probe:
            self.fail_probe = False
            raise RuntimeError("health failed")

    def run_deploy(self, token="secret"):
        return deploy(token=token, install=self.install, execute=self.execute,
                      probe=self.probe, executable=self.executable,
                      runtime=self.root, backup_dir=self.root)

    def test_successful_deploy(self):
        self.run_deploy()
        self.assertEqual(self.executable.read_text(), "new")
        self.assertEqual(self.calls, ["install", "health"])
        self.assertEqual(sum(c[-1] == SERVICE and "restart" in c for c in self.commands), 1)

    def test_missing_token_fails_before_install(self):
        with self.assertRaises(ValueError):
            self.run_deploy(token="")
        self.assertEqual(self.calls, [])

    def test_missing_bus_fails_before_install(self):
        (self.root / "bus").unlink()
        with self.assertRaises(RuntimeError):
            self.run_deploy()
        self.assertEqual(self.calls, [])

    def test_backup_failure_prevents_install(self):
        def fail_copy(*args):
            if args[:3] == ("sudo", "-n", "cp"):
                raise PermissionError("backup denied")
            self.execute(*args)
        with self.assertRaisesRegex(PermissionError, "backup denied"):
            deploy(token="secret", install=self.install, execute=fail_copy,
                   probe=self.probe, executable=self.executable,
                   runtime=self.root, backup_dir=self.root)
        self.assertEqual(self.executable.read_text(), "old")
        self.assertEqual(self.calls, [])

    def test_failed_install_rolls_back(self):
        def broken():
            self.executable.write_text("broken")
            raise RuntimeError("install failed")
        self.install = broken
        with self.assertRaisesRegex(RuntimeError, "install failed"):
            self.run_deploy()
        self.assertEqual(self.executable.read_text(), "old")
        self.assertEqual(self.executable.stat().st_mode & 0o777, 0o750)
        self.assertTrue(any(c[:3] == ("sudo", "-n", "chown") and c[-1] == str(self.executable) for c in self.commands))

    def test_failed_restart_rolls_back(self):
        self.fail_restart = True
        with self.assertRaisesRegex(RuntimeError, "restart failed"):
            self.run_deploy()
        self.assertEqual(self.executable.read_text(), "old")
        self.assertEqual(sum("restart" in c for c in self.commands), 2)

    def test_failed_health_rolls_back(self):
        self.fail_probe = True
        with self.assertRaisesRegex(RuntimeError, "health failed"):
            self.run_deploy()
        self.assertEqual(self.executable.read_text(), "old")
        self.assertEqual(self.calls, ["install", "health", "health"])

    def test_failed_rollback_is_reported(self):
        self.fail_probe = True
        def broken(*args):
            if args[:3] == ("sudo", "-n", "install"):
                raise PermissionError("restore denied")
            self.execute(*args)
        with self.assertRaisesRegex(RuntimeError, "rollback verification failed"):
            deploy(token="secret", install=self.install, execute=broken,
                   probe=self.probe, executable=self.executable,
                   runtime=self.root, backup_dir=self.root)


if __name__ == "__main__":
    unittest.main()
