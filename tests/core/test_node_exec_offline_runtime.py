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

    def test_sqlite_restart_preserves_records_and_rejects_unsafe_reopen(self):
        """Simulate a worker restart by reopening durable state, never dispatch jobs."""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "private"
            directory.mkdir(mode=0o700)
            path = directory / "jobs.sqlite3"
            first = worker.Jobs(path, max_active=1)
            with first.connection() as db:
                db.execute(
                    "INSERT INTO jobs (id,node,command,status,created_at) VALUES (?,?,?,?,?)",
                    ("a" * 32, "gway-001", "true", "queued", "2026-01-01T00:00:00+00:00"))
            restarted = worker.Jobs(path, max_active=1)
            self.assertEqual(restarted.row("a" * 32)["status"], "queued")
            with restarted.connection() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
            path.chmod(0o666)
            with self.assertRaises(PermissionError):
                with restarted.connection():
                    pass

    def test_effective_uid_mismatch_denied_before_worker(self):
        from gway_remote import node_exec_identity
        from types import SimpleNamespace
        with patch.object(worker, "selected_user", return_value="installer"), \
             patch.object(worker.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=1001)), \
             patch.object(worker.os, "geteuid", return_value=1002):
            with self.assertRaisesRegex(PermissionError, "effective user mismatch"):
                worker.require_account()
        with patch.object(node_exec_identity, "selected_user", return_value="installer"), \
             patch.object(node_exec_identity.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=1001)), \
             patch.object(node_exec_identity.os, "geteuid", return_value=1002):
            with self.assertRaises(PermissionError):
                node_exec_identity.command_environment()

    def test_user_manager_fails_closed_without_runtime(self):
        with patch.object(worker, "require_account"), \
             patch.object(worker.os, "geteuid", return_value=os.geteuid()), \
             patch.object(worker.Path, "lstat", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "user manager unavailable"):
                worker.user_manager_env()

    def test_user_bus_positive_and_unsafe_socket_negative_offline(self):
        """A synthetic user bus must be owned by the same nonroot UID."""
        import stat
        from types import SimpleNamespace
        runtime = Path("/run/user/1001")
        bus = runtime / "bus"
        real_lstat = Path.lstat

        def probe(path, *, directory_owner=1001, directory_mode=0o700,
                  bus_owner=1001, bus_type=stat.S_IFSOCK):
            candidate = Path(path)
            if candidate == runtime:
                return SimpleNamespace(st_mode=stat.S_IFDIR | directory_mode,
                                       st_uid=directory_owner)
            if candidate == bus:
                return SimpleNamespace(st_mode=bus_type | 0o600, st_uid=bus_owner)
            return real_lstat(path)

        def check(**changes):
            with patch.object(worker, "require_account"), \
                 patch.object(worker.os, "geteuid", return_value=1001), \
                 patch.object(worker.pwd, "getpwuid",
                              return_value=SimpleNamespace(pw_dir="/home/installer", pw_name="installer")), \
                 patch.object(Path, "lstat", autospec=True,
                              side_effect=lambda path: probe(path, **changes)):
                return worker.user_manager_env()

        environment = check()
        self.assertEqual(environment["XDG_RUNTIME_DIR"], "/run/user/1001")
        self.assertEqual(environment["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/user/1001/bus")
        self.assertEqual(environment["USER"], "installer")
        self.assertNotIn("SSH_AUTH_SOCK", environment)
        for altered in ({"directory_owner": 0}, {"directory_mode": 0o722},
                        {"bus_owner": 0}, {"bus_type": stat.S_IFREG}):
            with self.subTest(altered=altered), \
                 self.assertRaisesRegex(RuntimeError, "user manager unavailable"):
                check(**altered)

    def test_mocked_user_systemd_launch_limits_and_replay_after_restart(self):
        """Capture systemd-run argv only: no user manager, child, or shell runs."""
        from types import SimpleNamespace
        from gway_remote.node_exec_contract import DEFAULT_LIMITS
        job_id = "c" * 32
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "private"
            directory.mkdir(mode=0o700)
            path = directory / "jobs.sqlite3"
            jobs = worker.Jobs(path, max_active=1)
            launches = []

            def capture(argv, **kwargs):
                launches.append((argv, kwargs))
                return SimpleNamespace(returncode=0)

            with patch.object(worker, "require_account"), \
                 patch.object(worker, "user_manager_env",
                              return_value={"PATH": "/usr/bin:/bin", "USER": "installer"}):
                self.assertEqual(jobs.submit("gway-001", "true", request_id=job_id,
                                             execute=capture), job_id)
                argv, kwargs = launches[0]
                self.assertEqual(argv[:3], ["systemd-run", "--user", "--collect"])
                self.assertIn("--property=MemoryMax=" + str(DEFAULT_LIMITS["memory_max_bytes"]), argv)
                self.assertIn("--property=TasksMax=" + str(DEFAULT_LIMITS["tasks_max"]), argv)
                self.assertIn("--property=RuntimeMaxSec=" + str(worker.JOB_TIMEOUT + 10), argv)
                self.assertIn("--property=KillMode=control-group", argv)
                self.assertIn("--setenv=PYTHONPATH=/opt/gway-remote", argv)
                self.assertEqual(kwargs["timeout"], 10)
                self.assertEqual(kwargs["env"]["USER"], "installer")
                self.assertNotIn("SSH_AUTH_SOCK", kwargs["env"])
                restarted = worker.Jobs(path, max_active=1)
                self.assertEqual(restarted.submit("gway-001", "true", request_id=job_id,
                                                 execute=capture), job_id)
                self.assertEqual(len(launches), 1)
                with self.assertRaises(ValueError):
                    restarted.submit("gway-001", "false", request_id=job_id,
                                     execute=capture)
                with self.assertRaisesRegex(RuntimeError, "executor busy"):
                    restarted.submit("gway-001", "true", request_id="d" * 32,
                                     execute=capture)
                # A disappeared transient unit must NOT be re-run after restart.
                def inactive(argv, **kwargs):
                    self.assertEqual(argv[:3], ["systemctl", "--user", "show"])
                    return SimpleNamespace(stdout="inactive\\n")
                self.assertEqual(restarted.reconcile(job_id, execute=inactive), "unknown")
                self.assertEqual(len(launches), 1)

    def test_root_owned_executor_limit_override_positive_and_negative(self):
        import stat
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "executor.json"
            original_lstat = Path.lstat
            def read_as_root(value, *, owner=0, mode=0o644):
                config.write_text(__import__("json").dumps(value))
                config.chmod(mode)
                def fake_stat(path):
                    info = original_lstat(path)
                    if Path(path) == config:
                        return SimpleNamespace(st_mode=info.st_mode, st_uid=owner)
                    return info
                with patch.object(Path, "lstat", autospec=True, side_effect=fake_stat), \
                     patch.object(worker.os, "cpu_count", return_value=4):
                    return worker.configured_max_active(config)
            self.assertEqual(read_as_root({"max_active": "auto"}), 3)
            self.assertEqual(read_as_root({"max_active": 2}), 2)
            for config_value in ({"max_active": 0}, {"max_active": 9},
                                 {"max_active": True}, {"max_active": "2"},
                                 {"max_active": 1, "run_as": "root"}):
                with self.subTest(config_value=config_value), self.assertRaises(ValueError):
                    read_as_root(config_value)
            with self.assertRaises(PermissionError):
                read_as_root({"max_active": 2}, owner=1001)
            with self.assertRaises(PermissionError):
                read_as_root({"max_active": 2}, mode=0o666)

    def test_concurrency_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "private"
            directory.mkdir(mode=0o700)
            for limit in (0, 9, True, "2"):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    worker.Jobs(directory / "jobs.sqlite3", max_active=limit)


if __name__ == "__main__":
    unittest.main()
