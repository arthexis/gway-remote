"""Local B2b-1 durability and per-node concurrency tests; no real systemd jobs."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.node_exec_worker import Jobs, configured_max_active


class DurableRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        self.database = self.root / "jobs.sqlite3"
        account = patch("gway_remote.node_exec_worker.require_account")
        account.start()
        self.addCleanup(account.stop)
        self.launches = []

    def launcher(self, argv, **kwargs):
        self.launches.append(argv)
        return None

    def submit(self, jobs, rid, command="echo safe", node="gway-001"):
        return jobs.submit(node, command, request_id=rid, execute=self.launcher)

    def test_retry_same_request_does_not_relaunch(self):
        jobs = Jobs(self.database, max_active=1)
        rid = "a" * 32
        self.assertEqual(self.submit(jobs, rid), rid)
        self.assertEqual(self.submit(Jobs(self.database, max_active=1), rid), rid)
        self.assertEqual(len(self.launches), 1)

    def test_terminal_retry_does_not_relaunch(self):
        jobs = Jobs(self.database, max_active=1)
        rid = "b" * 32
        self.submit(jobs, rid)
        with jobs.connection() as db:
            db.execute("UPDATE jobs SET status='succeeded' WHERE id=?", (rid,))
        self.assertEqual(self.submit(jobs, rid), rid)
        self.assertEqual(len(self.launches), 1)

    def test_reused_id_different_node_or_command_is_conflict(self):
        jobs = Jobs(self.database, max_active=2)
        rid = "c" * 32
        self.submit(jobs, rid)
        for node, cmd in (("gway-002", "echo safe"), ("gway-001", "echo different")):
            with self.subTest(node=node):
                with self.assertRaisesRegex(ValueError, "request ID conflict"):
                    self.submit(jobs, rid, cmd, node)
        self.assertEqual(len(self.launches), 1)

    def test_per_node_cap_and_slot_release(self):
        jobs = Jobs(self.database, max_active=2)
        self.submit(jobs, "1" * 32)
        self.submit(jobs, "2" * 32)
        with self.assertRaisesRegex(RuntimeError, "executor busy"):
            self.submit(jobs, "3" * 32)
        # Retries are safe even if there are no free slots.
        self.assertEqual(self.submit(jobs, "1" * 32), "1" * 32)
        # Caller-supplied node metadata must not bypass this appliance's cap.
        with self.assertRaisesRegex(RuntimeError, "executor busy"):
            self.submit(jobs, "4" * 32, node="gway-002")
        with jobs.connection() as db:
            db.execute("UPDATE jobs SET status='succeeded' WHERE id=?", ("1" * 32,))
        self.submit(jobs, "3" * 32)
        self.assertEqual(len(self.launches), 3)

    def test_invalid_request_ids_cannot_launch(self):
        jobs = Jobs(self.database, max_active=1)
        for rid in ("f" * 31, "f" * 33, "G" * 32, "", 0, True):
            with self.subTest(rid=rid), self.assertRaises(ValueError):
                self.submit(jobs, rid)
        self.assertFalse(self.launches)

    def test_auto_concurrency_reserves_one_core(self):
        absent = self.root / "absent.json"
        for cpu, expected in ((None, 1), (1, 1), (2, 1), (4, 3), (8, 7), (16, 8)):
            with self.subTest(cpu=cpu), patch(
                "gway_remote.node_exec_worker.os.cpu_count", return_value=cpu
            ):
                self.assertEqual(configured_max_active(absent), expected)

    def test_root_controlled_override_bounds(self):
        # The policy file must be root-owned in production. For test fixtures
        # explicitly patch file metadata to simulate root ownership.
        policy = self.root / "executor.json"
        policy.write_text('{"max_active": 5}\n')
        real_lstat = Path.lstat
        with patch("gway_remote.node_exec_worker.Path.lstat") as mock_lstat:
            def fixture_lstat(path):
                info = real_lstat(path)
                if Path(path) == policy:
                    return type("Info", (), {"st_mode": info.st_mode,
                                              "st_uid": 0})()
                return info
            mock_lstat.side_effect = fixture_lstat
            self.assertEqual(configured_max_active(policy), 5)
            policy.write_text('{"max_active": "auto"}\n')
            with patch("gway_remote.node_exec_worker.os.cpu_count", return_value=4):
                self.assertEqual(configured_max_active(policy), 3)
            for bad in (0, 9, True, 1.5, "four"):
                policy.write_text(json.dumps({"max_active": bad}))
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    configured_max_active(policy)

    def test_no_automatic_execution_endpoint(self):
        from gway_remote import node_exec_worker
        self.assertFalse(hasattr(node_exec_worker, "node_exec"))
        self.assertFalse(hasattr(node_exec_worker, "mcp_execute"))


if __name__ == "__main__":
    unittest.main()
