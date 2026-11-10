"""Authenticated bridge deployment dispatch regression tests (no network)."""
import unittest
from unittest.mock import patch

from gway_remote.mcp_bridge_gateway_dispatch import dispatch_node_tool

RID = "a" * 32


class BridgeDeploymentTests(unittest.TestCase):
    def test_deployment_reply_must_be_signed_and_correlated(self):
        for name in ("node_deploy", "node_deploy_status"):
            with self.subTest(name=name):
                captured = {}
                def fake_call(path, key, envelope, **kwargs):
                    captured.update(kwargs)
                    return {"request_id": RID, "node": "gway-001", "status": "dispatched"}
                with patch("gway_remote.mcp_bridge_gateway_dispatch.call_unix", side_effect=fake_call):
                    response = dispatch_node_tool(socket_path="/private", key=b"k", session_id="session",
                        audience="gway-001", principal="principal", name=name,
                        arguments={"node": "gway-001", "application": "agentops", "request_id": RID})
                self.assertTrue(captured["require_signed_reply"])
                self.assertEqual(response["request_id"], RID)

    def test_wrong_reply_identity_denied(self):
        with patch("gway_remote.mcp_bridge_gateway_dispatch.call_unix",
                   return_value={"request_id": "b" * 32, "node": "gway-001"}):
            with self.assertRaises(PermissionError):
                dispatch_node_tool(socket_path="/private", key=b"k", session_id="session",
                    audience="gway-001", principal="principal", name="node_deploy",
                    arguments={"node": "gway-001", "application": "agentops", "request_id": RID})

    def test_invalid_request_id_and_cross_node_denied_before_transport(self):
        with patch("gway_remote.mcp_bridge_gateway_dispatch.call_unix") as call:
            for arguments in ({"node": "gway-001", "application": "agentops", "request_id": "bad"},
                              {"node": "gway-002", "application": "agentops", "request_id": RID}):
                with self.assertRaises((ValueError, PermissionError)):
                    dispatch_node_tool(socket_path="/private", key=b"k", session_id="session",
                        audience="gway-001", principal="principal", name="node_deploy",
                        arguments=arguments)
            call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
