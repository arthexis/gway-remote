"""Node-local execution policy regression tests."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from gway_remote import node_exec_identity as identity
from gway_remote import node_exec_worker as worker


class ExecutorIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.policy = Path(self.temp.name) / "identity.json"

    def read_policy(self, value, node):
        self.policy.write_text(json.dumps({"user": value}))
        original = Path.lstat

        def root_owned(path):
            meta = original(path)
            if Path(path) == self.policy:
                return type("Stat", (), {"st_mode": meta.st_mode, "st_uid": 0})()
            return meta

        with patch.object(Path, "lstat", autospec=True, side_effect=root_owned):
            return identity.selected_user(self.policy, hostname=node)

    def test_default_and_explicit_pilot(self):
        self.assertEqual(identity.selected_user(self.policy), "gway-exec")
        self.assertEqual(self.read_policy("arthe", "gway-001"), "arthe")
        self.assertEqual(self.read_policy("gway-exec", "gway-005"), "gway-exec")

    def test_operator_is_rejected_on_other_nodes(self):
        with self.assertRaises(PermissionError):
            self.read_policy("arthe", "gway-005")

    def test_unrecognized_users_rejected(self):
        for user in ("root", "ubuntu", "", None):
            with self.subTest(user=user), self.assertRaises(PermissionError):
                self.read_policy(user, "gway-001")

    def test_world_writable_configuration_rejected(self):
        self.policy.write_text('{"user":"arthe"}')
        self.policy.chmod(0o666)
        with self.assertRaises(PermissionError):
            identity.selected_user(self.policy, hostname="gway-001")

    def test_job_database_is_distinct_per_identity(self):
        self.assertEqual(identity.state_dir("gway-exec") / "jobs.sqlite3", worker.DEFAULT_STATE)
        self.assertNotEqual(identity.state_dir("arthe"), identity.state_dir("gway-exec"))
        with patch.object(worker, "selected_user", return_value="gway-exec"), patch.object(worker, "configured_max_active", return_value=1):
            # Verify path selection separately from real host directory permissions.
            with patch.object(worker.Jobs, "_validate_dir"):
                self.assertEqual(worker.Jobs().path, worker.DEFAULT_STATE)
        with patch.object(worker, "selected_user", return_value="arthe"), patch.object(worker, "configured_max_active", return_value=1):
            with patch.object(worker.Jobs, "_validate_dir"):
                self.assertEqual(worker.Jobs().path, identity.state_dir("arthe") / "jobs.sqlite3")


if __name__ == "__main__":
    unittest.main()
