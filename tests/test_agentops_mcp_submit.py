"""AgentOps MCP submit boundary regression tests."""
import json
import unittest
from unittest.mock import patch

from gway_remote import mcp_agent, mcp_bearer_gateway


class AgentSubmitMcpTests(unittest.TestCase):
    def test_submit_is_discovered_and_not_read_only(self):
        tools = {tool["name"]: tool for tool in mcp_agent.list_tools()}
        self.assertIn("agent_submit", tools)
        self.assertNotIn("readOnlyHint", tools["agent_submit"].get("annotations", {}))
        self.assertEqual(set(tools["agent_submit"]["inputSchema"]["required"]), {"ref", "at"})
        self.assertIn("agent_submit", mcp_bearer_gateway.ALLOWED_TOOLS)

    def test_submit_reuses_existing_adapter_and_frozen_identity(self):
        args = {"ref": "arthexis/gway-bastion#8", "at": "2026-11-05T20:00:00Z"}
        with patch("gway_remote.agent_ops_adapter._run", return_value={"status": "ok"}) as run:
            mcp_agent.call_tool("agent_submit", args)
        run.assert_called_once_with([
            "submit", args["ref"], "--at", "2026-11-05T20:00:00.000000Z",
            "--origin", "remote-api"])

    def test_rejects_invalid_arguments_without_dispatch(self):
        for args in ({}, {"ref": "arthexis/gway-bastion#8"},
                     {"ref": "arthexis/gway-bastion#8", "at": "tomorrow"},
                     {"ref": "arthexis/gway-bastion#8", "at": "2026-11-05T20:00:00Z", "extra": 1}):
            with self.subTest(args=args), patch("gway_remote.agent_ops_adapter._run") as run:
                with self.assertRaises(ValueError):
                    mcp_agent.call_tool("agent_submit", args)
                run.assert_not_called()

    def test_submit_classified_as_execution(self):
        payload = json.dumps({"jsonrpc": "2.0", "method": "tools/call",
                              "params": {"name": "agent_submit", "arguments": {}}})
        self.assertTrue(mcp_bearer_gateway.payload_is_exec(payload))
        self.assertTrue(mcp_bearer_gateway.inspect_rpc(payload))


if __name__ == "__main__":
    unittest.main()
