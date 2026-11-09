"""Offline end-to-end signed read-only deployment diagnostic propagation."""
import io
import json
import unittest
from unittest.mock import Mock, patch

from gway_remote.mcp_bridge_session import SessionBridgeDispatch
from gway_remote.mcp_bridge_transport import BridgeReadUnavailable, call_unix, canonical, sign_reply


class DeploymentDiagnosticBridgeTests(unittest.TestCase):
    def test_dispatcher_allowlists_only_sanitized_codes(self):
        verifier = Mock()
        verifier.verify.return_value = True
        dispatcher = SessionBridgeDispatch(
            verifier=verifier, session_token="trusted",
            allowed_node=lambda token, node: True,
            read_principal=lambda token: "b"*24,
            execution=Mock())
        envelope = {"audience": "gway-001", "scope": "gway:read",
                    "principal": "b"*24, "operation": "deployment.preview",
                    "arguments": {"node": "gway-001", "application": "sample"}}
        for code in ("deployment_inventory_binding_denied",
                     "deployment_pinned_transport_unavailable",
                     "deployment_ssh_unverified",
                     "deployment_node_protocol_unavailable",
                     "deployment_declaration_unavailable",
                     "deployment_execution_disabled"):
            dispatcher.execution.deployment_preview.side_effect = PermissionError(code)
            with self.subTest(code=code), self.assertRaises(BridgeReadUnavailable) as raised:
                dispatcher(envelope)
            self.assertEqual(raised.exception.code, code)
        dispatcher.execution.deployment_preview.side_effect = PermissionError("secret private path")
        with self.assertRaises(PermissionError) as raised:
            dispatcher(envelope)
        self.assertNotIsInstance(raised.exception, BridgeReadUnavailable)

    def test_hmac_signed_error_survives_gateway_dispatch(self):
        from gway_remote.mcp_bridge_gateway_dispatch import dispatch_node_tool
        key = b"k"*32
        code = "deployment_inventory_binding_denied"

        class Socket:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def settimeout(self, timeout):
                pass
            def connect(self, path):
                pass
            def sendall(self, payload):
                request = json.loads(payload)
                body = {"ok": False, "error": "read_unavailable", "code": code}
                self.reply = canonical({**body, "reply_signature":
                    sign_reply(key, request["signature"], body)}) + b"\n"
            def makefile(self, mode):
                return io.BytesIO(self.reply)

        with patch("gway_remote.mcp_bridge_transport.socket.socket", return_value=Socket()):
            with self.assertRaises(BridgeReadUnavailable) as raised:
                dispatch_node_tool(socket_path="/offline", key=key, session_id="session",
                    audience="gway-001", principal="b"*24,
                    name="node_deploy_preview",
                    arguments={"node": "gway-001", "application": "sample"})
        self.assertEqual(raised.exception.code, code)

    def test_unsigned_or_tampered_error_is_rejected(self):
        key = b"k"*32
        envelope = {"version": 1, "request_id": "a"*32, "principal": "b"*24,
                    "audience": "gway-001", "operation": "deployment.preview",
                    "scope": "gway:read", "issued_at": 1, "expires_at": 30,
                    "arguments": {"node": "gway-001", "application": "sample"}}
        class Socket:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def settimeout(self, timeout):
                pass
            def connect(self, path):
                pass
            def sendall(self, payload):
                self.reply = canonical({"ok": False, "error": "read_unavailable",
                                        "code": "deployment_ssh_unverified",
                                        "reply_signature": "0"*64}) + b"\n"
            def makefile(self, mode):
                return io.BytesIO(self.reply)
        with patch("gway_remote.mcp_bridge_transport.socket.socket", return_value=Socket()):
            with self.assertRaises(PermissionError) as raised:
                call_unix("/offline", key, envelope, session_id="session",
                          require_signed_reply=True)
        self.assertNotIsInstance(raised.exception, BridgeReadUnavailable)


if __name__ == "__main__":
    unittest.main()
