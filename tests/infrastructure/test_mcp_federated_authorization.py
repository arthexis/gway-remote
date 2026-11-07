"""Node-authoritative federation and caller-scope regression tests."""
import unittest

from gway_remote.mcp_federated_catalog import catalog_from_nodes, route_provider_call


def catalog():
    return {"gway-001": {"node": "gway-001", "providers": [{
        "provider": "odoo", "node": "gway-001", "revision": "a" * 40,
        "status": "available", "tools": [
            {"name": "contacts_list", "inputSchema": {"type": "object"},
             "annotations": {"readOnlyHint": True}},
            {"name": "contacts_update", "inputSchema": {"type": "object"}},
        ]}]}}


class FederationAuthorizationTests(unittest.TestCase):
    def test_node_tools_need_no_watchtower_allowlist(self):
        tools, routes = catalog_from_nodes([], catalog())
        self.assertEqual({t["name"] for t in tools},
                         {"odoo__contacts_list", "odoo__contacts_update"})
        self.assertEqual(routes["odoo__contacts_update"][3], "execute")

    def test_read_token_cannot_execute_node_tool(self):
        _, routes = catalog_from_nodes([], catalog())
        called = []
        with self.assertRaises(PermissionError):
            route_provider_call(routes, "odoo__contacts_update", {},
                                authorized_scope="read",
                                invoke=lambda *a, **kw: called.append((a, kw)))
        self.assertEqual(called, [])

    def test_execute_token_can_call_node_tool(self):
        _, routes = catalog_from_nodes([], catalog())
        called = []
        route_provider_call(routes, "odoo__contacts_update", {"id": 1},
                            authorized_scope="execute",
                            invoke=lambda *a, **kw: called.append((a, kw)))
        self.assertEqual(called[0][1]["trusted_scope"], "execute")

    def test_node_cannot_shadow_builtin(self):
        with self.assertRaises(ValueError):
            catalog_from_nodes([{"name": "odoo__contacts_list",
                                 "inputSchema": {"type": "object"}}], catalog())


if __name__ == "__main__":
    unittest.main()
