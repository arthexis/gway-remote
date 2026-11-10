"""Behavioral offline tests for the isolated user manager and SQLite state."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gway_remote import node_exec_worker as worker


class WorkerOfflineTests(unittest.TestCase):
    def test_private_sqlite_creation_and_idempotent_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "private"
            directory.mkdir(mode=0o700)
            path = directory / "fresh.sqlite3"
            jobs = worker.Jobs(path, max_active=1)
            with jobs.connection() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)
                db.execute("INSERT INTO job_tombstones (id,node,command_sha256,status) VALUES (?,?,?,?)",
                           ("a"*32, "gway-001", "b"*64, "succeeded"))
            with jobs.connection() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM job_tombstones").fetchone()[0], 1)
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            path.chmod(0o644)
            with self.assertRaises(PermissionError):
                with jobs.connection():
                    pass

    def test_state_directory_denies_world_access_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "private"
            directory.mkdir(mode=0o700)
            path = directory / "jobs.sqlite3"
            directory.chmod(0o755)
            with self.assertRaises(PermissionError):
                worker.Jobs(path, max_active=1)
            directory.chmod(0o700)
            path.symlink_to(Path(tmp) / "elsewhere")
            with self.assertRaises(PermissionError):
                worker.Jobs(path, max_active=1)

    def test_user_manager_fails_closed_without_runtime(self):
        with patch.object(worker, "require_account"), \
             patch.object(worker.os, "geteuid", return_value=os.geteuid()), \
             patch.object(worker.Path, "lstat", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "user manager unavailable"):
                worker.user_manager_env()

    def test_concurrency_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "private"
            directory.mkdir(mode=0o700)
            for limit in (0, 9, True, "2"):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    worker.Jobs(directory / "jobs.sqlite3", max_active=limit)


if __name__ == "__main__":
    unittest.main()
