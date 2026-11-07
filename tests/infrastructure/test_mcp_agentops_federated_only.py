"""Regression: AgentOps is owned by the federated node, never built into Remote."""
import unittest

from gway_remote import mcp_agent


LEGACY = {
    "agent_list_issues", "agent_status", "agent_preview",
    "agent_submit", "agent_observe",
}


class FederatedAgentOpsOnly(unittest.TestCase):
    def test_legacy_tools_are_not_builtins(self):
        self.assertFalse(LEGACY.intersection(tool["name"] for tool in mcp_agent.TOOLS))
        self.assertFalse(LEGACY.intersection(mcp_agent._HANDLERS))

    def test_legacy_dispatch_rejected(self):
        for name in LEGACY:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "mcp_tool_not_allowed"):
                    mcp_agent.call_tool(name, {}, authorized_scope="execute")


if __name__ == "__main__":
    unittest.main()
