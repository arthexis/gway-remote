"""Federated discovery fail-closed and partial outage regression tests."""
import unittest

from gway_remote.mcp_gateway_federation import FederatedProviders
from gway_remote.mcp_federated_catalog import FederationError, catalog_from_nodes


from tests.helpers.mcp_provider import provider_reply as reply, InvocationSpy
from tests.helpers.mcp_federation import fixture_tool


class FederationFailureTests(unittest.TestCase):
    def test_unreachable_node_does_not_hide_healthy_node(self):
        transport = InvocationSpy(fail_node='gway-002')
        tools, routes = FederatedProviders(
            transport=transport, nodes=lambda: ("gway-001", "gway-002")).discover()
        self.assertEqual([tool["name"] for tool in tools], ["odoo__list"])
        self.assertEqual(routes["odoo__list"][0], "gway-001")
        self.assertEqual({call[0] for call in transport.calls}, {"gway-001", "gway-002"})

    def test_invalid_catalog_does_not_silently_disappear(self):
        transport = InvocationSpy(response={'node': 'wrong', 'providers': []})
        with self.assertRaises(FederationError):
            FederatedProviders(transport=transport,
                               nodes=lambda: ("gway-001",)).discover()

    def test_duplicate_provider_across_nodes_is_rejected(self):
        with self.assertRaises(FederationError):
            catalog_from_nodes([], {"gway-001": reply("gway-001"),
                                    "gway-002": reply("gway-002", tools=[{
                                        "name": "update", "inputSchema": {"type": "object"}}])})

    def test_invalid_tool_schema_rejected(self):
        with self.assertRaises(FederationError):
            catalog_from_nodes([], {"gway-001": reply("gway-001", tools=[{
                "name": "list", "inputSchema": {"type": "string"}}])})


if __name__ == "__main__":
    unittest.main()
