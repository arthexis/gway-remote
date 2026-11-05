"""B2a local job implementation tests: no real systemd, shell or network."""
import os
from pathlib import Path
import pwd
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gway_remote import node_exec_worker as worker


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "jobs"
        self.directory.mkdir(mode=0o700)
        self.store = worker.Jobs(self.directory / "jobs.sqlite3")
        self.identity = patch.object(worker, "require_account", return_value=None)
        self.identity.start()
        self.addCleanup(self.identity.stop)

    def submit(self, command="uptime", runner=None):
        if runner is None:
            runner = lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", "")
        return self.store.submit("gway-001", command, execute=runner)

    def test_submit_requires_systemd_user_scope_with_cgroup_and_fixed_worker_argv(self):
        captured = []
        def run(args, **kwargs):
            captured.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, "", "")
        cmd = "df -h && echo 'literal'"
        with patch.object(worker, "selected_user", return_value="gway-exec"):
            job_id = self.submit(cmd, runner=run)
        args, kwargs = captured[0]
        self.assertEqual(args[:3], ["systemd-run", "--user", "--collect"])
        self.assertIn("--setenv=PYTHONPATH=/opt/gway-remote", args)
        self.assertIn("--working-directory=/var/lib/gway-exec", args)
        self.assertIn("--property=KillMode=control-group", args)
        self.assertIn("--property=MemoryMax=134217728", args)
        self.assertIn("--property=TasksMax=32", args)
        self.assertEqual(args[-2:], ["--run", job_id])
        self.assertNotIn(cmd, " ".join(args))
        self.assertEqual(self.store.row(job_id)["command"], cmd)
        self.assertEqual(self.store.row(job_id)["status"], "queued")
        self.assertEqual(kwargs["timeout"], 10)
        self.assertEqual(self.store.result(job_id)["status"], "queued")

    def test_submit_fails_closed_if_systemd_cannot_launch(self):
        def failed(*args, **kwargs):
            raise subprocess.CalledProcessError(1, args[0])
        with self.assertRaisesRegex(RuntimeError, "launch failed"):
            self.submit(runner=failed)
        with self.store.connection() as db:
            row = db.execute("SELECT status FROM jobs").fetchone()
        self.assertEqual(row[0], "failed")

    def test_no_second_concurrent_job_with_one_slot_policy(self):
        self.store.max_active = 1  # Explicit old-policy regression, auto is CPU-based.
        self.submit("sleep 10")
        with self.assertRaisesRegex(RuntimeError, "busy"):
            self.submit("echo another")

    def test_cancel_request_uses_exact_systemd_unit_no_submitted_shell(self):
        job_id = self.submit("sleep 20")
        calls = []
        def capture(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")
        self.assertEqual(self.store.cancel(job_id, execute=capture), "cancel_requested")
        self.assertEqual(calls[0], ["systemctl", "--user", "kill", "--kill-whom=main",
                                    "--signal=SIGUSR1", worker.unit_name(job_id)])
        self.assertNotIn("sleep 20", str(calls[0]))
        self.assertTrue(self.store.row(job_id)["cancel_requested"])

    def test_reconcile_terminated_unrecorded_job_is_unknown_not_replayed(self):
        job_id = self.submit("uptime")
        def stopped(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, "inactive\n", "")
        self.assertEqual(self.store.reconcile(job_id, execute=stopped), "unknown")
        self.assertEqual(self.store.row(job_id)["status"], "unknown")
        # Reconciliation must not automatically recreate any work.
        self.assertEqual(self.store.row(job_id)["status"], "unknown")

    def test_reconcile_cancelled_job_is_marked_cancelled(self):
        job_id = self.submit("sleep 20")
        self.store.cancel(job_id, execute=lambda args, **kwargs:
                          subprocess.CompletedProcess(args, 0, "", ""))
        def stopped(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, "inactive\n", "")
        self.assertEqual(self.store.reconcile(job_id, execute=stopped), "cancelled")

    def test_result_cursor_and_output_bound(self):
        job_id = self.submit()
        with self.store.connection() as db:
            db.execute("UPDATE jobs SET status='succeeded',exit_code=0,output=? WHERE id=?",
                       (b"A" * 20000, job_id))
        first = self.store.result(job_id)
        self.assertEqual(len(first["stdout"]), 16384)
        self.assertEqual(first["cursor"], "16384")
        second = self.store.result(job_id, cursor=16384)
        self.assertEqual(len(second["stdout"]), 3616)
        self.assertIsNone(second["cursor"])
        for cursor in (-1, 9999999, "0"):
            with self.assertRaises(ValueError):
                self.store.result(job_id, cursor=cursor)

    def test_worker_completes_shell_command_and_persists_output(self):
        job_id = self.submit("printf 'ready\\n' && printf 'diagnostic\\n' >&2")
        self.assertEqual(worker.worker(self.store.path, job_id), 0)
        result = self.store.result(job_id)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("ready", result["stdout"])
        self.assertIn("diagnostic", result["stdout"])

    def test_cancel_running_worker_persists_terminal_state_promptly(self):
        import threading
        import time
        job_id = self.submit("sleep 20")
        runner = threading.Thread(target=worker.worker, args=(self.store.path, job_id))
        runner.start()
        try:
            for _ in range(100):
                if self.store.row(job_id)["status"] == "running":
                    break
                time.sleep(0.02)
            self.assertEqual(self.store.row(job_id)["status"], "running")
            started = time.monotonic()
            result = self.store.cancel(
                job_id, execute=lambda args, **kwargs:
                subprocess.CompletedProcess(args, 0, "", ""))
            self.assertEqual(result, "cancel_requested")
            runner.join(timeout=5)
            self.assertFalse(runner.is_alive())
            self.assertLess(time.monotonic() - started, 5)
            final = self.store.result(job_id)
            self.assertEqual(final["status"], "cancelled")
            self.assertIsNone(final["exit_code"])
            self.assertIsNotNone(final["finished_at"])
        finally:
            runner.join(timeout=2)

    def test_job_history_capacity_compacts_terminal_results_without_replay(self):
        with self.store.connection() as db:
            for index in range(worker.MAX_HISTORY):
                db.execute("INSERT INTO jobs (id,node,command,status,created_at) VALUES (?,?,?,?,?)",
                           (f"{index:032x}", "gway-001", "true", "succeeded", worker.utcnow()))
        self.submit("uptime")
        old = "0" * 32
        result = self.store.result(old)
        self.assertFalse(result["result_available"])
        self.assertEqual(result["reason"], "result_expired")
        self.assertEqual(result["status"], "succeeded")
        with patch.object(worker, "user_manager_env", side_effect=AssertionError("replayed")):
            self.assertEqual(self.store.submit("gway-001", "true", request_id=old), old)
            with self.assertRaisesRegex(ValueError, "conflict"):
                self.store.submit("gway-001", "different", request_id=old)

    def test_full_tombstone_ledger_fails_closed(self):
        with self.store.connection() as db:
            for index in range(worker.MAX_HISTORY):
                db.execute("INSERT INTO jobs (id,node,command,status,created_at) VALUES (?,?,?,?,?)",
                           (f"{index:032x}", "gway-001", "true", "succeeded", worker.utcnow()))
        with patch.object(worker, "MAX_TOMBSTONES", 0), self.assertRaisesRegex(RuntimeError, "capacity"):
            self.submit("uptime")

    def test_storage_permissions_and_symlink_rejected(self):
        link = self.directory / "link"
        link.symlink_to(self.directory / "jobs.sqlite3")
        with self.assertRaises(PermissionError):
            worker.Jobs(link)
        self.directory.chmod(0o755)
        with self.assertRaises(PermissionError):
            worker.Jobs(self.directory / "jobs.sqlite3")

    def test_job_ids_are_strict_and_cannot_be_service_names_or_paths(self):
        for value in ("../../foo", "gway-001", "1" * 33, "", "x" * 32):
            with self.assertRaises(ValueError):
                worker.unit_name(value)
                self.store.row(value)


if __name__ == "__main__":
    unittest.main()
