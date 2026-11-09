"""Causal evidence cannot change the durable uncertain dispatch state."""
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from gway_remote.watchtower_exec_transport import DormantRelay, SSHTransportFailure


class CausalRelayTests(unittest.TestCase):
    def setUp(self):
        self.request_id = "a" * 32
        self.ledger = Mock()
        self.ledger.get.return_value = {
            "node": "gway-001", "host_key_sha256": "b" * 64,
            "state": "reserved", "command": "true",
        }
        self.transport = Mock()
        self.transport.node = SimpleNamespace(node="gway-001",
                                               host_key_sha256="b" * 64)
        self.relay = DormantRelay(self.ledger, self.transport, enabled=True)

    def test_authorized_execution_returns_bounded_stage(self):
        from unittest.mock import patch
        from gway_remote.watchtower_exec_auth import AuthorizedExecution
        execution = AuthorizedExecution(self.ledger, None, self.relay, enabled=True)
        self.ledger.get.side_effect = [ValueError("request not found"),
                                       self.ledger.get.return_value]
        self.transport.invoke.side_effect = SSHTransportFailure("private")
        with patch.object(execution, "_allow"), \
             patch.object(execution, "_current_eligibility"), \
             patch("gway_remote.watchtower_exec_auth.validate_command"):
            result = execution.exec(principal="c" * 24,
                                    request_id=self.request_id,
                                    node="gway-001", command="true",
                                    wait_seconds=0)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["failure_stage"], "ssh_transport")
        self.assertEqual(result["request_id"], self.request_id)
        self.assertNotIn("private", str(result))

    def test_typed_ssh_failure_preserves_uncertain(self):
        self.transport.invoke.side_effect = SSHTransportFailure("private")
        result = self.relay.dispatch(self.request_id)
        self.assertEqual(result, {"status": "uncertain",
                                  "failure_stage": "ssh_transport"})
        self.ledger.mark_dispatched.assert_called_once_with(
            self.request_id, confirmed=False)
        self.assertEqual(self.transport.invoke.call_count, 1)

    def test_generic_ssh_failure_remains_unclassified(self):
        self.transport.invoke.side_effect = subprocess.CalledProcessError(
            255, ["ssh"], stderr=b"secret")
        self.assertEqual(self.relay.dispatch(self.request_id), "uncertain")
        self.assertEqual(self.transport.invoke.call_count, 1)

    def test_worker_stage_requires_matching_node_and_job(self):
        for node, request_id, expected in (
            ("gway-001", self.request_id, True),
            ("gway-002", self.request_id, False),
            ("gway-001", "c" * 32, False),
        ):
            with self.subTest(node=node, request_id=request_id):
                self.ledger.reset_mock()
                self.transport.invoke.reset_mock()
                self.transport.invoke.side_effect = None
                self.transport.invoke.return_value = {
                    "node": node, "request_id": request_id,
                    "status": "rejected", "failure_stage": "worker_readiness"}
                result = self.relay.dispatch(self.request_id)
                self.assertEqual(
                    result, {"status": "uncertain",
                             "failure_stage": "worker_readiness"}
                    if expected else "uncertain")
                self.ledger.mark_dispatched.assert_called_once_with(
                    self.request_id, confirmed=False)


if __name__ == "__main__":
    unittest.main()
