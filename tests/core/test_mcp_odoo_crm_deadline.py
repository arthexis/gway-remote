"""CRM-specific scope and deadline regression; no business or network I/O."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from gway_remote.mcp_node_providers import NodeProviderError, provider_call
from gway_remote.mcp_federated_catalog import catalog_from_nodes, route_provider_call
from gway_remote.mcp_source_registry import SourceRegistration

READ = ["crm_stage_list", "crm_team_list", "crm_opportunity_get", "crm_opportunity_search"]
WRITE = ["crm_opportunity_create", "crm_opportunity_update", "crm_opportunity_stage_move"]
TOOLS = [{"name": n, "inputSchema": {"type": "object"},
          "annotations": {"readOnlyHint": n in READ}} for n in READ + WRITE]
REG = SourceRegistration("odoo", "a" * 40, "/usr/bin/true",
                         ("/usr/bin/true",), "arthe", True)


class TestOdooCRMDeadline(unittest.TestCase):
    def test_crm_write_scope_and_bounded_deadline(self):
        for name in WRITE:
            with self.subTest(tool=name), patch(
                "gway_remote.mcp_node_providers._node_registration", side_effect=lambda r: r
            ), patch(
                "gway_remote.mcp_node_providers.list_source_tools", return_value=TOOLS
            ), patch(
                "gway_remote.mcp_node_providers.call_source_tool", return_value={"content": []}
            ) as invoke:
                with self.assertRaises(NodeProviderError) as exc:
                    provider_call([REG], provider="odoo", tool=name, arguments={}, authorized_scope="read")
                self.assertEqual(exc.exception.code, "permission_denied")
                invoke.assert_not_called()
                provider_call([REG], provider="odoo", tool=name, arguments={}, authorized_scope="execute")
                self.assertEqual(invoke.call_args.kwargs, {"authorized_scope": "execute", "timeout": 28})
                other = replace(REG, source_id="other")
                provider_call([other], provider="other", tool=name, arguments={}, authorized_scope="execute")
                self.assertEqual(invoke.call_args.kwargs, {"authorized_scope": "execute"})

    def test_crm_read_route_and_write_denial(self):
        node = "gway-001"
        _, routes = catalog_from_nodes([], {node: {"node": node, "providers": [
            {"provider": "odoo", "node": node, "revision": "a" * 40, "status": "available",
             "supports_provider_read": True, "tools": TOOLS}]}})
        calls = []

        def invoke(node, request, **kw):
            calls.append((node, request, kw))

        for name in WRITE:
            with self.subTest(tool=name), self.assertRaises(PermissionError):
                route_provider_call(routes, "odoo__" + name, {}, authorized_scope="read", invoke=invoke)
        self.assertFalse(calls)
        for name in READ:
            with self.subTest(tool=name):
                route_provider_call(routes, "odoo__" + name, {}, authorized_scope="read", invoke=invoke)
                self.assertEqual(calls[-1][1]["operation"], "provider_read")
                self.assertEqual(calls[-1][2]["trusted_scope"], "read")
