"""Offline stage-specific read-only deployment preview diagnostics."""
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gway_remote.watchtower_exec_auth import AuthorizedExecution
from gway_remote.watchtower_exec_transport import SSHTransportFailure


class DeploymentPreviewDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.auth = AuthorizedExecution(Mock(), None, SimpleNamespace(
            transport=Mock(), enabled=True), enabled=True)
        self.pinned = Mock()
        self.pinned.node.node = "gway-001"

    def call(self):
        return self.auth.deployment_preview(node="gway-001", application="sample")

    def test_disabled_does_not_touch_transport(self):
        self.auth.enabled = False
        with patch("gway_remote.watchtower_exec_auth.pinned_transport") as transport:
            with self.assertRaisesRegex(PermissionError, "deployment_execution_disabled"):
                self.call()
            transport.assert_not_called()

    def test_missing_pinned_transport(self):
        with patch.object(self.auth, "_allow_preview_eligibility"):
          with patch("gway_remote.watchtower_exec_auth.pinned_transport",
                     side_effect=PermissionError("sensitive host path")):
            with self.assertRaisesRegex(PermissionError, "^deployment_pinned_transport_unavailable$"):
                self.call()

    def test_inventory_binding_denied_before_ssh(self):
        with patch("gway_remote.watchtower_exec_auth.pinned_transport", return_value=self.pinned):
            with patch.object(self.auth, "_allow_preview_eligibility",
                              side_effect=PermissionError("secret address")):
                with self.assertRaisesRegex(PermissionError, "^deployment_inventory_binding_denied$"):
                    self.call()
                self.pinned.invoke.assert_not_called()

    def test_ssh_and_protocol_failures_are_sanitized(self):
        with patch("gway_remote.watchtower_exec_auth.pinned_transport", return_value=self.pinned):
            with patch.object(self.auth, "_allow_preview_eligibility"):
                for error, expected in (
                    (SSHTransportFailure("host key secret"), "deployment_ssh_unverified"),
                    (subprocess.CalledProcessError(255, ["ssh"]), "deployment_ssh_unverified"),
                    (ValueError("private response"), "deployment_node_protocol_unavailable"),
                ):
                    with self.subTest(expected=expected):
                        self.pinned.invoke.side_effect = error
                        with self.assertRaisesRegex(PermissionError, "^" + expected + "$"):
                            self.call()

    def test_invalid_or_missing_declaration(self):
        with patch("gway_remote.watchtower_exec_auth.pinned_transport", return_value=self.pinned):
            with patch.object(self.auth, "_current_eligibility"):
                def response(payload):
                    return {"node": "gway-001", "request_id": payload["request_id"],
                            "result": {"application": "sample", "status": "not_declared"}}
                self.pinned.invoke.side_effect = response
                with self.assertRaisesRegex(PermissionError, "^deployment_declaration_unavailable$"):
                    self.call()

    def test_valid_preview(self):
        with patch("gway_remote.watchtower_exec_auth.pinned_transport", return_value=self.pinned):
            with patch.object(self.auth, "_current_eligibility"):
                def response(payload):
                    return {"node": "gway-001", "request_id": payload["request_id"],
                            "result": {"application": "sample", "status": "declared",
                                       "revision": "a"*40}}
                self.pinned.invoke.side_effect = response
                self.assertEqual(self.call()["revision"], "a"*40)


if __name__ == "__main__":
    unittest.main()
