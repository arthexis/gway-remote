"""Read-only federated MCP catalog diagnostic contract."""
import unittest

from gway_remote.mcp_bearer_gateway import (
    ALLOWED_TOOLS, NODE_TOOLS, inspect_federated_catalog,
)


class FakeFederation:
    def discover(self, builtins=()):
        return (list(builtins) + [{
            "name": "agentops__submit",
            "inputSchema": {"type": "object"},
        }, {
            "name": "agentops__status",
            "inputSchema": {"type": "object"},
            "annotations": {"readOnlyHint": True},
        }], {
            "agentops__submit": ("gway-001", "agentops", "submit", "execute"),
            "agentops__status": ("gway-001", "agentops", "status", "read"),
        })


class CatalogInspectTests(unittest.TestCase):
    def test_read_only_tool_is_advertised(self):
        self.assertIn("mcp_catalog_inspect", ALLOWED_TOOLS)
        tool = next(t for t in NODE_TOOLS if t["name"] == "mcp_catalog_inspect")
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertEqual(tool["inputSchema"]["properties"], {})

    def test_scope_and_origin_without_arguments_or_secrets(self):
        result = inspect_federated_catalog(FakeFederation(), builtins=[
            {"name": "mcp_catalog_inspect", "inputSchema": {"type": "object"}}
        ])
        tools = {t["name"]: t for t in result["tools"]}
        self.assertEqual(tools["agentops__submit"]["required_scope"], "gway:execute")
        self.assertEqual(tools["agentops__status"]["required_scope"], "gway:read")
        self.assertEqual(tools["agentops__submit"]["node"], "gway-001")
        self.assertEqual(tools["mcp_catalog_inspect"]["origin"], "builtin")
        self.assertNotIn("inputSchema", tools["agentops__submit"])
        self.assertEqual(result["count"], 3)


if __name__ == "__main__":
    unittest.main()
