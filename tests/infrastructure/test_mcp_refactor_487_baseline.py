"""Characterize existing MCP federation contracts before refactoring (#487 A)."""
import unittest
from unittest.mock import patch

from gway_remote.mcp_bearer_gateway import inspect_federated_catalog
from gway_remote.mcp_node_providers import NodeProviderError, dispatch_node_provider_request


from tests.helpers.mcp_federation import FederationCatalogFixture, fixture_tool


def federation():
    return FederationCatalogFixture([
        fixture_tool('fixture__read', read=True),
        fixture_tool('fixture__write'),
    ], route_names={'fixture__read': 'read', 'fixture__write': 'write'})


class RefactorBaselineTests(unittest.TestCase):
    def test_catalog_projection_preserves_names_and_scopes(self):
        listed, _ = federation().discover()
        inspected = inspect_federated_catalog(federation())
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
