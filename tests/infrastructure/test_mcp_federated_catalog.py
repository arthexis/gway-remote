import unittest
from gway_remote.mcp_federated_catalog import (
    FederationError, catalog_from_nodes, route_provider_call,
)

from tests.helpers.mcp_federation import fixture_tool
from tests.helpers.mcp_provider import provider_reply, InvocationSpy

TOOL = fixture_tool('search', read=True)


def nodes(*names, tool=TOOL):
    return {name: provider_reply(name, tools=[tool]) for name in names}


class FederatedCatalogTests(unittest.TestCase):
    def test_routes_to_authenticated_node(self):
        tools, routes = catalog_from_nodes([], nodes('gway-001'))
        self.assertEqual([t["name"] for t in tools], ["odoo__search"])
        spy = InvocationSpy(response={'ok': True})
        self.assertEqual(route_provider_call(routes, "odoo__search", {},
                                              authorized_scope="read", invoke=spy.invoke),
                         {"ok": True})
        self.assertEqual(spy.calls[0][0], "gway-001")
        self.assertEqual(spy.calls[0][1]["operation"], "provider_call")
        self.assertEqual(spy.calls[0][2], "read")

    def test_duplicate_provider_tool_rejected(self):
        with self.assertRaises(FederationError):
            catalog_from_nodes([], nodes('gway-001', 'gway-002'))


    def test_unknown_tool_rejected(self):
        _, routes = catalog_from_nodes([], {})
        with self.assertRaises(FederationError):
            route_provider_call(routes, "odoo__search", {}, authorized_scope="read",
                                invoke=lambda *a, **kw: None)

    def test_execute_scope_enforced(self):
        execute = {**TOOL, "annotations": {"readOnlyHint": False}}
        _, routes = catalog_from_nodes([], nodes('gway-001', tool=execute))
        with self.assertRaises(PermissionError):
            route_provider_call(routes, "odoo__search", {}, authorized_scope="read",
                                invoke=lambda *a, **kw: None)


if __name__ == "__main__":
    unittest.main()
