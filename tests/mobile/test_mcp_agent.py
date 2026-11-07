"""MCP builtin contract: AgentOps is provided only by node federation."""
import unittest
from unittest.mock import Mock, patch
from gway_remote import mcp_agent

LEGACY = {"agent_list_issues", "agent_status", "agent_preview", "agent_observe", "agent_submit"}

class MCPAgentTests(unittest.TestCase):
    def test_tool_inventory_excludes_legacy(self):
        tools = mcp_agent.list_tools()
        names = {t["name"] for t in tools}
        self.assertFalse(LEGACY & names)
        self.assertTrue({"github_workflow_runs", "github_workflow_status", "github_workflow_errors", "mcp_source_status"} <= names)
        self.assertEqual(len(names), len(tools))

    def test_builtin_read_dispatch(self):
        with patch.dict(mcp_agent._HANDLERS, {"mcp_source_status": Mock(return_value={"status": "ok"})}):
            self.assertEqual(mcp_agent.call_tool("mcp_source_status", {}), {"status": "ok"})

    def test_legacy_names_cannot_dispatch(self):
        for name in LEGACY:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "mcp_tool_not_allowed"):
                mcp_agent.call_tool(name, {}, authorized_scope="execute")

if __name__ == "__main__":
    unittest.main()
