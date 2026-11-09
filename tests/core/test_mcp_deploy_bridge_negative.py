"""Offline negative tests for authenticated deployment gateway correlation."""
import unittest
from unittest.mock import patch

from gway_remote.mcp_bridge_gateway_dispatch import dispatch_node_tool


class DeploymentBridgeNegativeTests(unittest.TestCase):
    def invoke(self, *, tool="node_deploy", arguments=None, response=None):
        args = arguments or {"node": "gway-001", "request_id": "a"*32,
                             "application": "sample", "revision": "main"}
        if response is None:
            response = {"node": "gway-001", "request_id": "a"*32,
                        "status": "accepted"}
        with patch("gway_remote.mcp_bridge_gateway_dispatch.call_unix",
                   return_value=response) as call:
            result = dispatch_node_tool(
                socket_path="/not-connected", key=b"offline", session_id="session",
                audience="gway-001", principal="b"*24, name=tool, arguments=args)
            self.assertTrue(call.call_args.kwargs["require_signed_reply"])
            self.assertEqual(call.call_args.args[2]["scope"], "gway:execute")
            return result

    def test_deploy_and_status_require_signed_reply(self):
        self.invoke()
        self.invoke(tool="node_deploy_status")

    def test_rejects_cross_node_before_bridge(self):
        with patch("gway_remote.mcp_bridge_gateway_dispatch.call_unix") as call:
            with self.assertRaises(PermissionError):
                self.invoke(arguments={"node": "gway-002", "request_id": "a"*32})
            call.assert_not_called()

    def test_rejects_uncorrelated_signed_response(self):
        for response in (
            {"node": "gway-002", "request_id": "a"*32},
            {"node": "gway-001", "request_id": "c"*32},
            {"node": "gway-001"},
        ):
            with self.subTest(response=response), self.assertRaises(PermissionError):
                self.invoke(response=response)

    def test_transport_signature_failure_is_not_accepted(self):
        with patch("gway_remote.mcp_bridge_gateway_dispatch.call_unix",
                   side_effect=PermissionError("invalid HMAC")):
            with self.assertRaises(PermissionError):
                dispatch_node_tool(
                    socket_path="/not-connected", key=b"offline", session_id="session",
                    audience="gway-001", principal="b"*24, name="node_deploy",
                    arguments={"node": "gway-001", "request_id": "a"*32,
                               "application": "sample", "revision": "main"})

    def test_real_hmac_reply_rejects_tampering_and_cross_request(self):
        import io
        import json
        from gway_remote.mcp_bridge_transport import call_unix, canonical, sign_reply

        key = b"k" * 32
        envelope = {"version": 1, "request_id": "a"*32,
                    "principal": "b"*24, "audience": "gway-001",
                    "operation": "deployment.start", "scope": "gway:execute",
                    "issued_at": 1, "expires_at": 30,
                    "arguments": {"node": "gway-001", "request_id": "c"*32,
                                  "application": "sample"}}

        class FakeSocket:
            def __init__(self, mode):
                self.mode = mode
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def settimeout(self, value):
                pass
            def connect(self, path):
                pass
            def sendall(self, payload):
                request = json.loads(payload)
                body = {"ok": True, "result": {"node": "gway-001",
                        "request_id": "c"*32, "status": "accepted"}}
                signature = sign_reply(key, request["signature"], body)
                if self.mode == "wrong-request":
                    signature = sign_reply(key, "0"*64, body)
                body["reply_signature"] = signature
                if self.mode == "tamper":
                    body["result"]["request_id"] = "d"*32
                self.reply = canonical(body) + b"\\n"
            def makefile(self, mode):
                return io.BytesIO(self.reply)

        for mode in ("tamper", "wrong-request"):
            with self.subTest(mode=mode):
                with patch("gway_remote.mcp_bridge_transport.socket.socket",
                           return_value=FakeSocket(mode)):
                    with self.assertRaises(PermissionError):
                        call_unix("/offline", key, envelope,
                                  require_signed_reply=True)

        with patch("gway_remote.mcp_bridge_transport.socket.socket",
                   return_value=FakeSocket("valid")):
            result = call_unix("/offline", key, envelope,
                               require_signed_reply=True)
            self.assertEqual(result["request_id"], "c"*32)


if __name__ == "__main__":
    unittest.main()
