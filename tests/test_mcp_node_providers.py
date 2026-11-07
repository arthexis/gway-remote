"""Node provider contract tests; no live Odoo credentials required."""
import unittest
from unittest.mock import patch

from gway_remote.mcp_node_providers import (
    NodeProviderError, provider_call, provider_list, dispatch_node_provider_request,
)
from gway_remote.mcp_source_registry import SourceRegistration


REG = SourceRegistration(source_id="odoo", revision="a" * 40,
                         executable="/usr/local/bin/odoo-mcp",
                         argv=("/usr/local/bin/odoo-mcp",),
                         run_as="arthe", enabled=True)
READ = {"name": "customer_search", "inputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True}}
WRITE = {"name": "customer_update", "inputSchema": {"type": "object"},
         "annotations": {"readOnlyHint": False}}


@patch("gway_remote.mcp_node_providers._assert_local_identity")
class NodeProviderTests(unittest.TestCase):
    @patch("gway_remote.mcp_node_providers.list_source_tools", return_value=[READ, WRITE])
    def test_local_catalog_includes_writes(self, discovery, identity):
        result = provider_list([REG], node_id="gway-001")
        self.assertEqual(result["node"], "gway-001")
        self.assertEqual({t["name"] for t in result["providers"][0]["tools"]},
                         {"customer_search", "customer_update"})
        self.assertEqual(result["providers"][0]["revision"], "a" * 40)

    @patch("gway_remote.mcp_node_providers.list_source_tools", return_value=[READ, WRITE])
    def test_write_requires_execute(self, discovery, identity):
        with self.assertRaises(NodeProviderError) as context:
            provider_call([REG], provider="odoo", tool="customer_update",
                          arguments={"id": 1}, authorized_scope="read")
        self.assertEqual(context.exception.code, "permission_denied")

    @patch("gway_remote.mcp_node_providers.call_source_tool", return_value={"content": []})
    @patch("gway_remote.mcp_node_providers.list_source_tools", return_value=[READ, WRITE])
    def test_authorized_write_is_dispatched(self, discovery, invoke, identity):
        result = provider_call([REG], provider="odoo", tool="customer_update",
                               arguments={"id": 1}, authorized_scope="execute")
        self.assertEqual(result, {"content": []})
        self.assertEqual(invoke.call_args.kwargs["authorized_scope"], "execute")

    @patch("gway_remote.mcp_node_providers.list_source_tools", side_effect=OSError())
    def test_failure_is_isolated(self, discovery, identity):
        result = provider_list([REG], node_id="gway-001")
        self.assertEqual(result["providers"][0]["status"], "unavailable")
        self.assertEqual(result["providers"][0]["tools"], [])
        self.assertEqual(result["providers"][0]["error"]["code"], "provider_unavailable")

    @patch("gway_remote.mcp_node_providers.list_source_tools", return_value=[READ, WRITE])
    def test_rpc_cannot_escalate_scope(self, discovery, identity):
        with self.assertRaises(NodeProviderError) as context:
            dispatch_node_provider_request(
                [REG], {"operation": "provider_call", "provider": "odoo",
                        "tool": "customer_update", "arguments": {"id": 1}},
                node_id="gway-001", trusted_scope="read")
        self.assertEqual(context.exception.code, "permission_denied")

    def test_rpc_rejects_scope_in_payload(self, identity):
        with self.assertRaises(NodeProviderError):
            dispatch_node_provider_request(
                [REG], {"operation": "provider_list", "authorized_scope": "execute"},
                node_id="gway-001", trusted_scope="read")

    def test_unregistered_provider_rejected(self, identity):
        with self.assertRaises(NodeProviderError):
            provider_call([REG], provider="other", tool="customer_search",
                          arguments={}, authorized_scope="read")


if __name__ == "__main__":
    unittest.main()
