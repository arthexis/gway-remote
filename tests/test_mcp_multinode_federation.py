"""Hermetic multi-node provider federation regression tests (#96)."""
import unittest

from gway_remote.mcp_federated_catalog import (
    FederationError, catalog_from_nodes, route_provider_call,
)


def reply(node, *, source="agentops", tools=None, revision="a" * 40):
    if tools is None:
        tools = [
            {"name": "status", "inputSchema": {"type": "object"},
             "annotations": {"readOnlyHint": True}},
            {"name": "submit", "inputSchema": {"type": "object"},
             "annotations": {"readOnlyHint": False}},
        ]
    return {"node": node, "providers": [{
        "node": node, "provider": source, "revision": revision,
        "status": "available", "tools": tools,
        "supports_provider_read": True,
    }]}


class MultiNodeFederationTests(unittest.TestCase):
    def test_001_preserved_and_004_qualified(self):
        tools, routes = catalog_from_nodes([], {
            "gway-001": reply("gway-001"),
            "gway-004": reply("gway-004")})
        names = {t["name"] for t in tools}
        self.assertEqual(names, {
            "agentops__status", "agentops__submit",
            "gway_004_agentops__status", "gway_004_agentops__submit"})
        self.assertEqual(routes["agentops__status"][:3], ("gway-001", "agentops", "status"))
        self.assertEqual(routes["gway_004_agentops__status"][:3],
                         ("gway-004", "agentops", "status"))
        sent = []
        def invoke(node, request, *, trusted_scope):
            sent.append((node, request, trusted_scope))
            return {"ok": True}
        route_provider_call(routes, "gway_004_agentops__status", {},
                            authorized_scope="read", invoke=invoke)
        self.assertEqual(sent[0][0], "gway-004")
        self.assertEqual(sent[0][1]["provider"], "agentops")
        self.assertEqual(sent[0][1]["operation"], "provider_read")
        with self.assertRaises(PermissionError):
            route_provider_call(routes, "gway_004_agentops__submit", {},
                                authorized_scope="read", invoke=invoke)
        self.assertEqual(len(sent), 1)

    def test_004_alone_keeps_stable_qualified_name(self):
        tools, routes = catalog_from_nodes([], {"gway-004": reply("gway-004")})
        self.assertEqual({t["name"] for t in tools},
                         {"gway_004_agentops__status", "gway_004_agentops__submit"})

    def test_collision_and_duplicate_on_same_node_fail_closed(self):
        response = reply("gway-004")
        response["providers"].append(dict(response["providers"][0]))
        with self.assertRaisesRegex(FederationError, "ambiguous_provider"):
            catalog_from_nodes([], {"gway-004": response})
        with self.assertRaisesRegex(ValueError, "duplicate tool name"):
            catalog_from_nodes([{"name": "gway_004_agentops__status",
                                    "inputSchema": {"type": "object"}}],
                               {"gway-004": reply("gway-004")})


if __name__ == "__main__":
    unittest.main()
