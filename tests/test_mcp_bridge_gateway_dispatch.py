import unittest
from unittest.mock import patch
from gway_remote.mcp_bridge_gateway_dispatch import dispatch_node_tool, OPERATIONS

class GatewayDispatchTests(unittest.TestCase):
    def test_operation_catalog(self):
        self.assertEqual(len(OPERATIONS), 9)
        self.assertEqual(OPERATIONS["node_exec"], ("execution.start", "gway:execute"))

    def test_session_binding(self):
        with patch("gway_remote.mcp_bridge_gateway_dispatch.call_unix", return_value={"ok": True}) as send:
            result = dispatch_node_tool(socket_path="/tmp/bridge.sock", key=b"k" * 32,
                session_id="a" * 48, audience="gway-001", principal="trusted",
                name="node_exec", arguments={"node": "gway-001", "command": "true", "request_id": "b" * 32})
            self.assertEqual(result, {"ok": True})
            self.assertEqual(send.call_args.kwargs["session_id"], "a" * 48)
            self.assertEqual(send.call_args.args[2]["operation"], "execution.start")

    def test_wrong_node_rejected(self):
        with patch("gway_remote.mcp_bridge_gateway_dispatch.call_unix") as send:
            with self.assertRaises(PermissionError):
                dispatch_node_tool(socket_path="/tmp/bridge.sock", key=b"k" * 32,
                    session_id="a" * 48, audience="gway-001", principal="trusted",
                    name="node_deploy", arguments={"node": "gway-002"})
            send.assert_not_called()

if __name__ == "__main__":
    unittest.main()
