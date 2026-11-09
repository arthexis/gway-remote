"""Signed bridge envelope nonce must not be confused with the job ID."""
import unittest
from unittest.mock import patch

from gway_remote.mcp_bridge_gateway_dispatch import dispatch_node_tool


class BridgeJobCorrelationTests(unittest.TestCase):
    def call(self, arguments):
        with patch("gway_remote.mcp_bridge_gateway_dispatch.call_unix") as send:
            send.return_value = {"status": "unknown"}
            result = dispatch_node_tool(
                socket_path="/unused", key=b"k" * 32, session_id="s" * 48,
                audience="gway-002", principal="p" * 24,
                name="node_exec", arguments=arguments)
            return result, send

    def test_signed_arguments_keep_job_id_distinct_from_replay_nonce(self):
        job_id = "a" * 32
        result, send = self.call({"node": "gway-002", "command": "true",
                                  "request_id": job_id})
        self.assertEqual(result["status"], "unknown")
        envelope = send.call_args.args[2]
        self.assertEqual(envelope["arguments"]["request_id"], job_id)
        self.assertNotEqual(envelope["request_id"], job_id)
        self.assertEqual(envelope["operation"], "execution.start")
        self.assertEqual(envelope["scope"], "gway:execute")

    def test_invalid_job_id_rejected_before_transport(self):
        for invalid in (None, "", "a" * 31, "A" * 32, 42):
            with self.subTest(invalid=invalid):
                with patch("gway_remote.mcp_bridge_gateway_dispatch.call_unix") as send:
                    with self.assertRaises(ValueError):
                        dispatch_node_tool(
                            socket_path="/unused", key=b"k" * 32,
                            session_id="s" * 48, audience="gway-002",
                            principal="p" * 24, name="node_exec",
                            arguments={"node": "gway-002", "command": "true",
                                       "request_id": invalid})
                    send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
