import unittest
from unittest.mock import patch

from gway_remote import mcp_agent
from gway_remote.mcp_bearer_gateway import inspect_rpc
from gway_remote.mcp_source_registry import SourceRegistration

TOOL = {"name": "ping", "description": "Read status",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True}}


class FederationIntegrationTests(unittest.TestCase):
    def tearDown(self):
        mcp_agent.configure_sources((), {})

    def test_default_is_unchanged(self):
        self.assertNotIn("odoo__ping", [t["name"] for t in mcp_agent.list_tools()])
        with self.assertRaises(ValueError):
            mcp_agent.call_tool("odoo__ping", {})

    def test_backend_namespaces_and_dispatches_approved_source(self):
        registration = SourceRegistration(
            source_id="odoo", revision="a" * 40, executable="/opt/odoo/bin/mcp",
            argv=("/opt/odoo/bin/mcp",), run_as="odoomcp", enabled=True)
        mcp_agent.configure_sources((registration,), {"odoo": (TOOL,)})
        self.assertIn("odoo__ping", [t["name"] for t in mcp_agent.list_tools()])
        with patch.object(mcp_agent, "call_source_tool", return_value={"content": []}) as call:
            self.assertEqual(mcp_agent.call_tool("odoo__ping", {}), {"content": []})
            self.assertEqual(call.call_args.args[1], "ping")
        with self.assertRaises(ValueError):
            mcp_agent.call_tool("odoo__unknown", {})

    def test_gateway_does_not_trust_advertised_names_by_default(self):
        import json
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "odoo__ping", "arguments": {}}}).encode()
        self.assertFalse(inspect_rpc(payload))
        self.assertTrue(inspect_rpc(payload, {"odoo__ping": {**TOOL, "name": "odoo__ping"}}))


if __name__ == "__main__":
    unittest.main()
