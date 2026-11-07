"""Live MCP federation: source admission is the only tool-discovery gate."""
import unittest
from unittest.mock import patch

from gway_remote import mcp_agent
from gway_remote.mcp_source_registry import SourceRegistration


class LiveSourceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.original = (mcp_agent._SOURCE_REGISTRATIONS, mcp_agent._SOURCE_APPROVED)
        self.source = SourceRegistration(source_id="odoo", revision="a" * 40,
            executable="/usr/bin/python3", argv=("/usr/bin/python3", "-m", "odoo_mcp"),
            run_as="arthe", enabled=True, permission="read")
        mcp_agent.configure_sources((self.source,), {"odoo": []})

    def tearDown(self):
        mcp_agent._SOURCE_REGISTRATIONS, mcp_agent._SOURCE_APPROVED = self.original

    @staticmethod
    def tool(name, readonly=True):
        return {"name": name, "inputSchema": {"type": "object"},
                "annotations": {"readOnlyHint": readonly, "destructiveHint": False}}

    def test_new_readonly_tool_appears_without_reapproval(self):
        with patch.object(mcp_agent, "list_source_tools", return_value=[self.tool("customer_search")]):
            names = [tool["name"] for tool in mcp_agent.list_tools()]
            self.assertIn("odoo__customer_search", names)
        with patch.object(mcp_agent, "list_source_tools", return_value=[
                self.tool("customer_search"), self.tool("product_search")]):
            self.assertIn("odoo__product_search", [tool["name"] for tool in mcp_agent.list_tools()])

    def test_removed_source_tool_disappears(self):
        with patch.object(mcp_agent, "list_source_tools", return_value=[]):
            self.assertFalse(any(t["name"].startswith("odoo__") for t in mcp_agent.list_tools()))

    def test_write_tool_is_withheld(self):
        with patch.object(mcp_agent, "list_source_tools", return_value=[self.tool("delete", False)]):
            self.assertNotIn("odoo__delete", [t["name"] for t in mcp_agent.list_tools()])
            with self.assertRaises(ValueError):
                mcp_agent.call_tool("odoo__delete", {})

    def test_source_outage_preserves_builtins(self):
        with patch.object(mcp_agent, "list_source_tools", side_effect=TimeoutError()):
            names = [t["name"] for t in mcp_agent.list_tools()]
            self.assertIn("agent_status", names)
            self.assertNotIn("odoo__customer_search", names)
            self.assertEqual(mcp_agent.source_status()["sources"][0]["status"], "unavailable")

    def test_live_call_rechecks_readonly_catalog(self):
        with patch.object(mcp_agent, "list_source_tools", return_value=[self.tool("customer_search")]), \
             patch.object(mcp_agent, "call_source_tool", return_value={"content": []}) as invoke:
            mcp_agent.call_tool("odoo__customer_search", {"query": "example"})
            self.assertEqual(invoke.call_args.args[1], "customer_search")


if __name__ == "__main__":
    unittest.main()
