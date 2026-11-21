import unittest
from gway_remote.mcp_federated_catalog import (
    FederationError, catalog_from_nodes, route_provider_call,
)

from tests.helpers.mcp_federation import fixture_tool
from tests.helpers.mcp_provider import provider_reply, InvocationSpy

TOOL = fixture_tool('search', read=True)


def nodes(*names, tool=TOOL):
    replies = {name: provider_reply(name, tools=[tool]) for name in names}
    for reply in replies.values():
        reply['providers'][0]['supports_provider_read'] = True
    return replies


class FederatedCatalogTests(unittest.TestCase):
    def test_routes_to_authenticated_node(self):
        tools, routes = catalog_from_nodes([], nodes('gway-001'))
        self.assertEqual([t["name"] for t in tools], ["odoo__search"])
        spy = InvocationSpy(response={'ok': True})
        self.assertEqual(route_provider_call(routes, "odoo__search", {},
                                              authorized_scope="read", invoke=spy.invoke),
                         {"ok": True})
        self.assertEqual(spy.calls[0][0], "gway-001")
        self.assertEqual(spy.calls[0][1]["operation"], "provider_read")
        self.assertEqual(spy.calls[0][2], "read")

    def test_same_provider_on_distinct_nodes_gets_distinct_routes(self):
        tools, routes = catalog_from_nodes([], nodes('gway-001', 'gway-002'))
        self.assertEqual({t["name"] for t in tools},
                         {"odoo__search", "gway_002_odoo__search"})
        self.assertEqual(routes["odoo__search"][0], "gway-001")
        self.assertEqual(routes["gway_002_odoo__search"][0], "gway-002")


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


    def test_advertised_read_rpc_uses_operation_bound_dispatch(self):
        reply = provider_reply('gway-001', tools=[TOOL, fixture_tool('update')])
        reply['providers'][0]['supports_provider_read'] = True
        _, routes = catalog_from_nodes([], {'gway-001': reply})
        spy = InvocationSpy(response={'content': []})
        self.assertEqual(route_provider_call(routes, 'odoo__search', {},
                                              authorized_scope='read',
                                              invoke=spy.invoke), {'content': []})
        self.assertEqual(spy.calls[0][1]['operation'], 'provider_read')
        self.assertNotIn('authorized_scope', spy.calls[0][1])

        # Even when read capability is supported, execution stays on provider_call.
        route_provider_call(routes, 'odoo__update', {'id': 1},
                            authorized_scope='execute', invoke=spy.invoke)
        self.assertEqual(spy.calls[1][1]['operation'], 'provider_call')

        # Read bearer never reaches a write tool or a remote node.
        with self.assertRaises(PermissionError):
            route_provider_call(routes, 'odoo__update', {},
                                authorized_scope='read', invoke=spy.invoke)
        self.assertEqual(len(spy.calls), 2)

    def test_legacy_receiver_read_fails_closed(self):
        for capability in (None, False):
            with self.subTest(capability=capability):
                reply = provider_reply('gway-001', tools=[TOOL])
                if capability is not None:
                    reply['providers'][0]['supports_provider_read'] = capability
                _, routes = catalog_from_nodes([], {'gway-001': reply})
                spy = InvocationSpy(response={'content': []})
                with self.assertRaisesRegex(FederationError, "provider_read_receiver_unsupported"):
                    route_provider_call(routes, 'odoo__search', {},
                                        authorized_scope='read', invoke=spy.invoke)
                self.assertEqual(spy.calls, [])
                # Write operations are still gated at public ingress.
                route_provider_call(routes, 'odoo__search', {},
                                    authorized_scope='execute', invoke=spy.invoke)
                self.assertEqual(spy.calls[0][1]['operation'], 'provider_call')

    def test_invalid_capability_fails_closed(self):
        for invalid in ('true', 1, None, [], {}):
            with self.subTest(invalid=invalid):
                reply = provider_reply('gway-001', tools=[TOOL])
                reply['providers'][0]['supports_provider_read'] = invalid
                with self.assertRaises(FederationError):
                    catalog_from_nodes([], {'gway-001': reply})


if __name__ == "__main__":
    unittest.main()
