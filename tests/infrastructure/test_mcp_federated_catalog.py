import unittest
from gway_remote.mcp_federated_catalog import (
    FederationError, catalog_from_nodes, route_provider_call,
)

TOOL = {"name": "search", "inputSchema": {"type": "object", "properties": {}}}


class FederatedCatalogTests(unittest.TestCase):
    def test_routes_to_authenticated_node(self):
        tools, routes = catalog_from_nodes([], {
            "gway-001": {"node": "gway-001", "providers": [{"provider": "odoo", "node": "gway-001", "revision": "a"*40, "status": "available", "tools": [TOOL]}]}})
        self.assertEqual([t["name"] for t in tools], ["odoo__search"])
        calls = []
        def invoke(node, request, *, trusted_scope):
            calls.append((node, request, trusted_scope))
            return {"ok": True}
        self.assertEqual(route_provider_call(routes, "odoo__search", {},
                                              authorized_scope="read", invoke=invoke),
                         {"ok": True})
        self.assertEqual(calls[0][0], "gway-001")
        self.assertEqual(calls[0][1]["operation"], "provider_call")
        self.assertEqual(calls[0][2], "read")

    def test_duplicate_provider_tool_rejected(self):
        with self.assertRaises(FederationError):
            catalog_from_nodes([], {
                "gway-001": {"node": "gway-001", "providers": [{"provider": "odoo", "node": "gway-001", "revision": "a"*40, "status": "available", "tools": [TOOL]}]},
                "gway-002": [{"provider": "odoo", "node": "gway-001", "revision": "a"*40, "status": "available", "tools": [TOOL]}]})

    def test_unknown_tool_rejected(self):
        _, routes = catalog_from_nodes([], {})
        with self.assertRaises(FederationError):
            route_provider_call(routes, "odoo__search", {}, authorized_scope="read",
                                invoke=lambda *a, **kw: None)

    def test_execute_scope_enforced(self):
        execute = {**TOOL, "annotations": {"readOnlyHint": False}}
        _, routes = catalog_from_nodes([], {
            "gway-001": {"node": "gway-001", "providers": [{"provider": "odoo", "node": "gway-001", "revision": "a"*40, "status": "available", "tools": [execute]}]}})
        with self.assertRaises(PermissionError):
            route_provider_call(routes, "odoo__search", {}, authorized_scope="read",
                                invoke=lambda *a, **kw: None)


if __name__ == "__main__":
    unittest.main()
