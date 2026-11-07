"""Federated discovery fail-closed and partial outage regression tests."""
import unittest

from gway_remote.mcp_gateway_federation import FederatedProviders
from gway_remote.mcp_federated_catalog import FederationError, catalog_from_nodes


def reply(node, source="odoo", tools=None):
    return {"node": node, "providers": [{
        "provider": source, "node": node, "revision": "a" * 40,
        "status": "available", "tools": tools if tools is not None else [{
            "name": "list", "inputSchema": {"type": "object"},
            "annotations": {"readOnlyHint": True}}]}]}


class FederationFailureTests(unittest.TestCase):
    def test_unreachable_node_does_not_hide_healthy_node(self):
        class Transport:
            def invoke(self, node, request, *, trusted_scope):
                if node == "gway-002":
                    raise TimeoutError("offline")
                return reply(node)
        tools, routes = FederatedProviders(
            transport=Transport(), nodes=lambda: ("gway-001", "gway-002")).discover()
        self.assertEqual([tool["name"] for tool in tools], ["odoo__list"])
        self.assertEqual(routes["odoo__list"][0], "gway-001")

    def test_invalid_catalog_does_not_silently_disappear(self):
        class Transport:
            def invoke(self, node, request, *, trusted_scope):
                return {"node": "wrong", "providers": []}
        with self.assertRaises(FederationError):
            FederatedProviders(transport=Transport(),
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
