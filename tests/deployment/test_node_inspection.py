"""Contract tests for private Watchtower identity and controller SSH gates."""
import subprocess
import unittest
from unittest.mock import Mock
from gway_remote.node_inspection import resolve_target, inspect_ssh


class NodeInspectionTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {"schema": 1, "nodes": [
            {"node": "gway-004", "address": "10.90.0.4/32", "state": "active"},
            {"node": "gway-005", "address": "10.90.0.5/32", "state": "revoked"},
        ]}

    def test_requires_explicit_approval(self):
        with self.assertRaises(ValueError):
            resolve_target(self.snapshot, "gway-004", set())
        self.assertEqual(resolve_target(self.snapshot, "gway-004", {"gway-004"}), "10.90.0.4")

    def test_revoked_ambiguous_and_public_rejected(self):
        with self.assertRaises(ValueError):
            resolve_target(self.snapshot, "gway-005", {"gway-005"})
        duplicate = {"schema": 1, "nodes": self.snapshot["nodes"] * 2}
        with self.assertRaises(ValueError):
            resolve_target(duplicate, "gway-004", {"gway-004"})
        public = {"schema": 1, "nodes": [{"node": "gway-004", "address": "8.8.8.8/32", "state": "active"}]}
        with self.assertRaises(ValueError):
            resolve_target(public, "gway-004", {"gway-004"})

    def test_ssh_probe_strict_and_read_only(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        self.assertEqual(inspect_ssh("gway-004", runner=runner)["ssh"], "verified")
        args = runner.call_args.args[0]
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertIn("BatchMode=yes", args)
        self.assertEqual(args[-2:], ["gway-004", "true"])
        self.assertNotIn("sudo", args)

    def test_ssh_fail_closed(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 255, "", ""))
        self.assertEqual(inspect_ssh("gway-004", runner=runner)["ssh"], "blocked")
        with self.assertRaises(ValueError):
            inspect_ssh("evil;rm -rf /", runner=runner)
