"""MCP read-only boundary and fixed adapter wiring."""
import unittest
from unittest.mock import patch, Mock

from gway_remote import mcp_agent


class MCPAgentTests(unittest.TestCase):
    def test_tool_inventory_is_read_only(self):
        tools = mcp_agent.list_tools()
        self.assertEqual({x["name"] for x in tools},
                         {"agent_list_issues", "agent_status", "agent_preview", "agent_observe"})
        self.assertTrue(all(x["annotations"]["readOnlyHint"] for x in tools))
        self.assertFalse(any("submit" in x["name"] for x in tools))

    def test_dispatches_only_fixed_read_operations(self):
        for name, handler, args in (
            ("agent_list_issues", "issues", {}),
            ("agent_status", "status", {}),
            ("agent_preview", "preview_issue", {"ref": "arthexis/gway-bastion#2"}),
            ("agent_observe", "observe_issue", {"ref": "arthexis/gway-bastion#2", "at": "2026-10-21T20:17:23Z"}),
        ):
            with self.subTest(name=name), patch.dict(mcp_agent._HANDLERS, {name: Mock(return_value={"status": "ok"})}):\n                operation = mcp_agent._HANDLERS[name]
                self.assertEqual(mcp_agent.call_tool(name, args), {"status": "ok"})
                operation.assert_called_once_with(args)

    def test_invalid_requests_never_reach_adapter(self):
        with patch.object(mcp_agent.agent_ops_adapter, "send_issue") as forbidden:
            for name, args in (
                ("agent_submit", {"ref": "arthexis/gway-bastion#2"}),
                ("agent_list_issues", {"unexpected": True}),
                ("agent_preview", {}),
                ("agent_observe", {"ref": "arthexis/gway-bastion#2"}),
                ("agent_status", None),
            ):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    mcp_agent.call_tool(name, args)
            forbidden.assert_not_called()


if __name__ == "__main__":
    unittest.main()
