"""Hermetic host-local flock tests; never touch installed host state."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from gway_remote.maintenance_lock import (
    Busy, Invalid, MaintenanceLock, Uncertain,
    MAX_WAIT_SECONDS, TOTAL_SECONDS, TARGET_SECONDS,
)
from gway_remote import maintenance_lock as module


class MaintenanceLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.uid = os.geteuid()
        self.mock_pwd = patch.object(
            module.pwd, "getpwuid",
            return_value=SimpleNamespace(pw_dir=str(self.home)),
        )
        self.mock_pwd.start()
        self.addCleanup(self.mock_pwd.stop)
        # Substitute only a temporary home. Root CI may exercise the isolated
        # primitive, while the unpatched production guard still refuses root.
        self.mock_operator = patch.object(module, "_operator_uid", return_value=self.uid)
        self.mock_operator.start()
        self.addCleanup(self.mock_operator.stop)

    def lock(self, wait=0):
        return MaintenanceLock(wait_seconds=wait)

    def state(self):
        path = self.home / ".local/state"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def test_production_root_guard(self):
        self.mock_operator.stop()
        try:
            with patch.object(module.os, "geteuid", return_value=0), self.assertRaises(Invalid):
                with self.lock():
                    pass
        finally:
            self.mock_operator.start()

    def test_boundaries(self):
        self.assertEqual((TARGET_SECONDS, TOTAL_SECONDS, MAX_WAIT_SECONDS), (180, 300, 20))
        for bad in (-1, 20.1, True, float("nan"), "5"):
            with self.subTest(bad=repr(bad)), self.assertRaises(Invalid):
                self.lock(bad)

    def test_create_acquire_release_keep_inode(self):
        with self.lock() as held:
            fd = held.fileno()
            p = self.home / ".local/state/maintenance.lock"
            self.assertTrue(p.is_file())
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                (p.stat().st_dev, p.stat().st_ino),
                (os.fstat(fd).st_dev, os.fstat(fd).st_ino),
            )
            self.assertLessEqual(held.remaining, TOTAL_SECONDS)
        self.assertTrue(p.exists())
        with self.lock() as again:
            self.assertGreaterEqual(again.fileno(), 0)

    def test_distinct_process_cannot_acquire_held_lock(self):
        code = """import fcntl,sys
with open(sys.argv[1], 'r+') as f:
    try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: sys.exit(3)
"""
        with self.lock():
            p = str(self.home / ".local/state/maintenance.lock")
            result = subprocess.run(
                [sys.executable, "-c", code, p], check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5,
            )
            self.assertEqual(result.returncode, 3)
        result = subprocess.run(
            [sys.executable, "-c", code, p], check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5,
        )
        self.assertEqual(result.returncode, 0)

    def test_state_symlink_is_denied(self):
        local = self.home / ".local"
        local.mkdir()
        (local / "state").symlink_to(self.home, target_is_directory=True)
        with self.assertRaises(Invalid):
            with self.lock():
                pass

    def test_second_acquisition_is_busy_without_changing_lock(self):
        with self.lock() as held:
            with self.assertRaises(Busy) as caught:
                with self.lock(wait=0.04):
                    pass
            self.assertEqual(caught.exception.exit_code, 3)
            self.assertTrue(os.path.exists(f"/proc/self/fd/{held.fileno()}"))

    def test_dup_fd_preserves_kernel_lock_after_supervisor_close(self):
        held = self.lock()
        held.__enter__()
        duplicate = os.dup(held.fileno())
        held.close()
        try:
            with self.assertRaises(Busy):
                with self.lock():
                    pass
        finally:
            os.close(duplicate)
        with self.lock():
            pass

    def test_symlink_and_hardlink_are_denied(self):
        state = self.state()
        other = self.home / "other"
        other.write_text("x")
        (state / "maintenance.lock").symlink_to(other)
        with self.assertRaises(Invalid):
            with self.lock():
                pass
        (state / "maintenance.lock").unlink()
        (state / "maintenance.lock").write_text("")
        (state / "maintenance.lock").chmod(0o600)
        os.link(state / "maintenance.lock", state / "alias")
        with self.assertRaises(Invalid):
            with self.lock():
                pass

    def test_untrusted_state_directory_and_lock_mode_are_denied(self):
        state = self.state()
        state.chmod(0o755)
        with self.assertRaises(Invalid):
            with self.lock():
                pass
        state.chmod(0o700)
        p = state / "maintenance.lock"
        p.write_text("")
        p.chmod(0o666)
        with self.assertRaises(Invalid):
            with self.lock():
                pass

    def test_name_substitution_rejected_while_held(self):
        with self.lock() as held:
            p = self.home / ".local/state/maintenance.lock"
            p.rename(p.with_suffix(".old"))
            p.write_text("")
            with self.assertRaises(Invalid):
                held.mark_uncertain("cleanup_failed")

    def test_unknown_reason_and_marker_blocks_future_admission(self):
        with self.lock() as held:
            with self.assertRaises(Invalid):
                held.mark_uncertain("untrusted injected text")
            held.mark_uncertain("remote_unverified")
            marker = self.home / ".local/state/maintenance.uncertain"
            self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
            self.assertIn('"reason": "remote_unverified"', marker.read_text())
            with self.assertRaises(Uncertain):
                held.mark_uncertain("cleanup_failed")
        with self.assertRaises(Uncertain):
            with self.lock():
                pass

    def test_remaining_is_monotonic_relative_to_one_start(self):
        with self.lock() as held:
            with patch.object(
                module.time, "monotonic",
                return_value=held.started + TOTAL_SECONDS + 1,
            ):
                self.assertEqual(held.remaining, 0.0)

    def test_nested_same_instance_rejected(self):
        with self.lock() as held:
            with self.assertRaises(Invalid):
                with held:
                    pass


if __name__ == "__main__":
    unittest.main()
