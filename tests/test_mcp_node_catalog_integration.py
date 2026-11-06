import unittest

from gway_remote import mcp_agent, mcp_http


class NodeCatalogIntegrationTests(unittest.TestCase):
    def test_http_lists_node_catalog(self):
        expected = mcp_agent.list_tools()
        result, error, message = mcp_http.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        self.assertIsNone(error, message)
        self.assertEqual(result["tools"], expected)
        self.assertEqual(len({tool["name"] for tool in expected}), len(expected))

    def test_invalid_tool_is_not_dispatched(self):
        result, error, message = mcp_http.handle(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "unknown_tool", "arguments": {}}})
        self.assertIsNone(result)
        self.assertEqual(error, -32602)

    def test_node_contract_is_not_modified_by_catalog_composition(self):
        first = mcp_agent.list_tools()
        first[0]["name"] = "tampered"
        self.assertNotEqual(mcp_agent.list_tools()[0]["name"], "tampered")


if __name__ == "__main__":
    unittest.main()
