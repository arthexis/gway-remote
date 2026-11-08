"""Characterize existing MCP federation contracts before refactoring (#487 A)."""
import unittest
from unittest.mock import patch

from gway_remote.mcp_bearer_gateway import inspect_federated_catalog
from gway_remote.mcp_node_providers import NodeProviderError, dispatch_node_provider_request


class FakeFederation:
    def discover(self, builtins=()):
        tools = list(builtins) + [
            {"name": "fixture__read", "inputSchema": {"type": "object"},
             "annotations": {"readOnlyHint": True}},
            {"name": "fixture__write", "inputSchema": {"type": "object"}},
        ]
        routes = {
            "fixture__read": ("gway-001", "fixture", "read", "read"),
            "fixture__write": ("gway-001", "fixture", "write", "execute"),
        }
        return tools, routes


class RefactorBaselineTests(unittest.TestCase):
    def test_catalog_projection_preserves_names_and_scopes(self):
        listed, _ = FakeFederation().discover()
        inspected = inspect_federated_catalog(FakeFederation())
        self.assertEqual([tool["name"] for tool in listed],
                         [tool["name"] for tool in inspected["tools"]])
        scopes = {tool["name"]: tool["required_scope"] for tool in inspected["tools"]}
        self.assertEqual(scopes["fixture__read"], "gway:read")
        self.assertEqual(scopes["fixture__write"], "gway:execute")
        for tool in inspected["tools"]:
            self.assertNotIn("inputSchema", tool)

    def test_node_rejects_untrusted_payload_scope(self):
        with self.assertRaises(NodeProviderError) as error:
            dispatch_node_provider_request(
                [], {"operation": "provider_list", "authorized_scope": "execute"},
                node_id="gway-001", trusted_scope="read")
        self.assertEqual(error.exception.code, "invalid_request")

    def test_provider_list_never_dispatches_tool_calls(self):
        with patch("gway_remote.mcp_node_providers.provider_call") as call:
            result = dispatch_node_provider_request(
                [], {"operation": "provider_list"},
                node_id="gway-001", trusted_scope="read")
        self.assertEqual(result["providers"], [])
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
