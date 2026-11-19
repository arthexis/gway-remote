"""#636: hermetic authorization-bound post-repair verification."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gway_remote.node_repair_verify import verify_limits, verify_terminal
from gway_remote.watchtower_exec_transport import SSHTransportFailure


RID = "a" * 32
NODE = "gway-002"


class VerifyRepairTests(unittest.TestCase):
    def authority(self, response=None, error=None):
        transport = Mock()
        if error is not None:
            transport.invoke.side_effect = error
        else:
            transport.invoke.return_value = response or {
                "node": NODE, "request_id": RID, "concurrent_jobs_per_node": 3}
        return SimpleNamespace(
            _allow_preview_eligibility=Mock(),
            relay=SimpleNamespace(transport=SimpleNamespace(node=SimpleNamespace(node=NODE))),
        ), transport

    def test_limits_success_uses_pinned_transport_only(self):
        authority, transport = self.authority()
        with patch("gway_remote.node_repair_verify.pinned_transport", return_value=transport) as pinned:
            report = verify_limits(authority, NODE, request_id_factory=lambda: RID)
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(report["concurrent_jobs_per_node"], 3)
        pinned.assert_called_once_with(authority.relay.transport, NODE)
        transport.invoke.assert_called_once_with({
            "operation": "limits", "node": NODE, "request_id": RID})
        authority._allow_preview_eligibility.assert_called_once_with(NODE)

    def test_limits_ssh_failure_is_after_the_attempt_and_sanitized(self):
        authority, transport = self.authority(error=SSHTransportFailure("secret key material"))
        with patch("gway_remote.node_repair_verify.pinned_transport", return_value=transport):
            result = verify_limits(authority, NODE, request_id_factory=lambda: RID)
        transport.invoke.assert_called_once()
        self.assertEqual(result["category"], "ssh_transport")
        self.assertNotIn("secret", str(result))

    def test_limits_wrong_response_is_protocol_not_success(self):
        authority, transport = self.authority(response={
            "node": NODE, "request_id": RID, "concurrent_jobs_per_node": "3"})
        with patch("gway_remote.node_repair_verify.pinned_transport", return_value=transport):
            result = verify_limits(authority, NODE, request_id_factory=lambda: RID)
        self.assertEqual(result["category"], "node_protocol")

    def test_limits_denied_before_ssh_without_bypassing_existing_grant(self):
        authority, transport = self.authority()
        authority._allow_preview_eligibility.side_effect = PermissionError("denied")
        with patch("gway_remote.node_repair_verify.pinned_transport", return_value=transport):
            result = verify_limits(authority, NODE, request_id_factory=lambda: RID)
        self.assertEqual(result["category"], "authorization_or_pin")
        transport.invoke.assert_not_called()

    def test_terminal_success_requires_exact_hostname_result(self):
        authority = Mock()
        authority.exec.return_value = {"node": NODE, "request_id": RID, "status": "dispatched"}
        authority.result.return_value = {"node": NODE, "request_id": RID, "status": "succeeded",
                                         "stdout": NODE + "\n", "exit_code": 0}
        output = verify_terminal(authority, principal="1" * 24, node=NODE,
                                 request_id_factory=lambda: RID)
        self.assertEqual(output["status"], "succeeded")
        authority.exec.assert_called_once_with(principal="1" * 24, request_id=RID,
                                               node=NODE, command="hostname", wait_seconds=10)
        authority.result.assert_called_once_with(principal="1" * 24, request_id=RID)

    def test_uncertain_submit_is_not_retried(self):
        authority = Mock()
        authority.exec.return_value = {"node": NODE, "request_id": RID,
                                       "status": "uncertain", "failure_stage": "ssh_transport"}
        authority.result.return_value = {"node": NODE, "request_id": RID, "status": "uncertain"}
        report = verify_terminal(authority, principal="1" * 24, node=NODE,
                                 request_id_factory=lambda: RID)
        self.assertEqual(report["status"], "uncertain")
        self.assertEqual(report["category"], "terminal_pending")
        authority.exec.assert_called_once()
        authority.result.assert_called_once()

    def test_terminal_wrong_node_not_accepted(self):
        authority = Mock()
        authority.exec.return_value = {"node": "gway-001", "request_id": RID, "status": "succeeded"}
        report = verify_terminal(authority, principal="1" * 24, node=NODE,
                                 request_id_factory=lambda: RID)
        self.assertEqual(report["category"], "uncorrelated_result")
        authority.result.assert_not_called()

    def test_terminal_exception_does_not_replay_or_leak(self):
        authority = Mock()
        authority.exec.side_effect = SSHTransportFailure("private key")
        report = verify_terminal(authority, principal="1" * 24, node=NODE,
                                 request_id_factory=lambda: RID)
        self.assertEqual(report["status"], "uncertain")
        self.assertEqual(report["category"], "ssh_transport")
        authority.exec.assert_called_once()
        authority.result.assert_not_called()
        self.assertNotIn("private key", str(report))


if __name__ == "__main__":
    unittest.main()
