"""Hermetic tests for canonical node routing primitives (#716)."""
import unittest

from gway_remote.mcp_federated_catalog import FederationError, catalog_from_nodes
from gway_remote.mcp_node_routing import canonical_node_index, resolve_node_route
from tests.test_mcp_multinode_federation import reply


class CanonicalNodeRoutingTests(unittest.TestCase):
    def build(self):
        tools, routes = catalog_from_nodes([], {
            "gway-001": reply("gway-001"),
            "gway-004": reply("gway-004"),
        })
        return canonical_node_index(tools, routes)

    def test_single_contract_and_explicit_execute(self):
        tools, index = self.build()
        self.assertEqual([tool["name"] for tool in tools],
                         ["agentops__status", "agentops__submit"])
        self.assertEqual(set(index["agentops__status"]), {"gway-001", "gway-004"})
        self.assertIn("node", tools[1]["inputSchema"]["required"])
        self.assertNotIn("node", tools[0]["inputSchema"].get("required", []))

    def test_selection_and_argument_stripping(self):
        _, index = self.build()
        args = {"node": "gway-004", "example": 1}
        route, downstream = resolve_node_route(index, "agentops__status", args)
        self.assertEqual(route[:3], ("gway-004", "agentops", "status"))
        self.assertEqual(downstream, {"example": 1})
        self.assertEqual(args["node"], "gway-004")

    def test_default_and_no_fallback(self):
        _, index = self.build()
        route, _ = resolve_node_route(index, "agentops__status", {},
                                      legacy_read_node="gway-001")
        self.assertEqual(route[0], "gway-001")
        with self.assertRaisesRegex(FederationError, "node_required"):
            resolve_node_route(index, "agentops__submit", {}, legacy_read_node="gway-001")
        with self.assertRaisesRegex(FederationError, "node_route_unavailable"):
            resolve_node_route(index, "agentops__status", {"node": "gway-999"},
                               legacy_read_node="gway-001")

    def test_incompatible_contract_fails_closed(self):
        other = reply("gway-004")
        other["providers"][0]["tools"][0]["inputSchema"]["properties"] = {
            "different": {"type": "string"}}
        tools, routes = catalog_from_nodes([], {
            "gway-001": reply("gway-001"), "gway-004": other})
        with self.assertRaisesRegex(FederationError, "incompatible_tool_contract"):
            canonical_node_index(tools, routes)

    def test_reserved_argument_fails_closed(self):
        other = reply("gway-004")
        other["providers"][0]["tools"][0]["inputSchema"]["properties"] = {
            "node": {"type": "string"}}
        tools, routes = catalog_from_nodes([], {"gway-004": other})
        with self.assertRaisesRegex(FederationError, "reserved_routing_argument"):
            canonical_node_index(tools, routes)
