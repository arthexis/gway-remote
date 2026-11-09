"""Offline SSH pinned-node deployment transport negative contracts."""
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from gway_remote.watchtower_exec_transport import SSHTransport


class DeploymentSSHNegativeTests(unittest.TestCase):
    def setUp(self):
        self.node = SimpleNamespace(node="gway-001",
                                    known_hosts="/pinned/known_hosts",
                                    ssh_host_alias="gway-001",
                                    identity_file="/pinned/identity",
                                    remote_user="gway-exec",
                                    wireguard_address="10.0.0.11")
        self.run = Mock()
        self.transport = SSHTransport(self.node, run=self.run)
        self.payload = {"operation": "deployment_run", "node": "gway-001",
                        "request_id": "a"*32, "application": "sample", "expected_revision": "a"*40}

    def test_exact_fields_and_pinned_node_before_ssh(self):
        for payload in (
            {**self.payload, "node": "gway-002"},
            {**self.payload, "runner": "/tmp/evil"},
            {**self.payload, "request_id": "invalid"},
            {**self.payload, "operation": "shell"},
            {k:v for k,v in self.payload.items() if k != "expected_revision"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.transport.invoke(payload)
        self.run.assert_not_called()

    def test_ssh_argv_never_includes_user_supplied_application(self):
        self.run.return_value = SimpleNamespace(stdout=json.dumps({
            "node": "gway-001", "request_id": "a"*32,
            "result": {"application": "sample", "state": "accepted"}}).encode())
        self.transport.invoke(self.payload)
        args, kwargs = self.run.call_args
        self.assertNotIn("sample", " ".join(args[0]))
        self.assertIn("StrictHostKeyChecking=yes", args[0])
        self.assertIn("ProxyCommand=none", args[0])
        self.assertIn("HostKeyAlias=gway-001", args[0])
        self.assertEqual(json.loads(kwargs["input"])["application"], "sample")

    def test_rejects_wrong_node_and_request_in_ssh_response(self):
        for node, rid in (("gway-002", "a"*32), ("gway-001", "b"*32)):
            self.run.return_value = SimpleNamespace(stdout=json.dumps({
                "node": node, "request_id": rid, "result": {}}).encode())
            with self.subTest(node=node, rid=rid), self.assertRaises(ValueError):
                self.transport.invoke(self.payload)

    def test_nonzero_ssh_exit_propagates_to_ledger_layer(self):
        self.run.side_effect = subprocess.CalledProcessError(255, ["ssh"])
        with self.assertRaises(subprocess.CalledProcessError):
            self.transport.invoke(self.payload)


if __name__ == "__main__":
    unittest.main()
