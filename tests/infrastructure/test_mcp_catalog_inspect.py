"""Read-only federated MCP catalog diagnostic contract."""
import unittest

from gway_remote.mcp_bearer_gateway import (
    ALLOWED_TOOLS, NODE_TOOLS, inspect_federated_catalog,
)


from tests.helpers.mcp_federation import FederationCatalogFixture, fixture_tool


def federation():
    return FederationCatalogFixture([
        fixture_tool('agentops__submit'),
        fixture_tool('agentops__status', read=True),
    ], source='agentops', route_names={
        'agentops__submit': 'submit', 'agentops__status': 'status',
    })


class CatalogInspectTests(unittest.TestCase):
    def test_read_only_tool_is_advertised(self):
        self.assertIn("mcp_catalog_inspect", ALLOWED_TOOLS)
        tool = next(t for t in NODE_TOOLS if t["name"] == "mcp_catalog_inspect")
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertEqual(tool["inputSchema"]["properties"], {})

    def test_namespaced_builtin_scope_matches_gateway_tools_list(self):
        result = inspect_federated_catalog(federation(), builtins=[
            {"name": "demo__mutate", "inputSchema": {"type": "object"}},
            {"name": "demo__read", "inputSchema": {"type": "object"},
             "annotations": {"readOnlyHint": True}},
        ])
        tools = {t["name"]: t for t in result["tools"]}
        self.assertEqual(tools["demo__mutate"]["required_scope"], "gway:execute")
        self.assertEqual(tools["demo__read"]["required_scope"], "gway:read")

    def test_scope_and_origin_without_arguments_or_secrets(self):
        result = inspect_federated_catalog(federation(), builtins=[
            {"name": "mcp_catalog_inspect", "inputSchema": {"type": "object"}}
        ])
        tools = {t["name"]: t for t in result["tools"]}
        self.assertEqual(tools["agentops__submit"]["required_scope"], "gway:execute")
        self.assertEqual(tools["agentops__status"]["required_scope"], "gway:read")
        self.assertEqual(tools["agentops__submit"]["node"], "gway-001")
        self.assertEqual(tools["mcp_catalog_inspect"]["origin"], "builtin")
        self.assertNotIn("inputSchema", tools["agentops__submit"])
        expected, _ = federation().discover(builtins=[
            {"name": "mcp_catalog_inspect", "inputSchema": {"type": "object"}}
        ])
        self.assertEqual(result["count"], len(expected))
        self.assertEqual([t["name"] for t in result["tools"]],
                         [t["name"] for t in expected])


if __name__ == "__main__":
    unittest.main()
