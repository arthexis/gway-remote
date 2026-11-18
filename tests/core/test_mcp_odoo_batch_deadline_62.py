"""Issue arthexis/odoo-gelectriic#62: isolated Odoo batch stdio deadline tests.

The existing provider and OAuth permissions are mocked. No Odoo I/O or PII.
"""
from dataclasses import replace
import unittest
from unittest.mock import patch

from gway_remote.mcp_node_providers import NodeProviderError, provider_call
from gway_remote.mcp_source_registry import SourceRegistration


REG = SourceRegistration(
    source_id="odoo", revision="a" * 40,
    executable="/usr/local/bin/odoo-mcp",
    argv=("/usr/local/bin/odoo-mcp",), run_as="arthe", enabled=True)
BATCH = {"name": "customer_vehicle_batch_apply",
         "inputSchema": {"type": "object"},
         "annotations": {"readOnlyHint": False}}
READ = {"name": "customer_search", "inputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True}}
WRITE = {"name": "customer_update", "inputSchema": {"type": "object"},
         "annotations": {"readOnlyHint": False}}


class OdooBatchDeadlineTests(unittest.TestCase):
    def test_batch_has_bounded_deadline_other_tools_keep_default(self):
        with patch("gway_remote.mcp_node_providers._node_registration",
                   side_effect=lambda registration: registration), \
             patch("gway_remote.mcp_node_providers.list_source_tools",
                   return_value=[READ, WRITE, BATCH]), \
             patch("gway_remote.mcp_node_providers.call_source_tool",
                   return_value={"content": []}) as invoke:
            batch = {"batch": {"schema_version": 1, "cases": []}}
            result = provider_call([REG], provider="odoo",
                                   tool="customer_vehicle_batch_apply", arguments=batch,
                                   authorized_scope="execute")
            self.assertEqual(result, {"content": []})
            self.assertEqual(invoke.call_args.kwargs,
                             {"authorized_scope": "execute", "timeout": 25})
            provider_call([REG], provider="odoo", tool="customer_update",
                          arguments={"id": 1}, authorized_scope="execute")
            self.assertEqual(invoke.call_args.kwargs, {"authorized_scope": "execute"})
            provider_call([REG], provider="odoo", tool="customer_search",
                          arguments={"query": "synthetic"}, authorized_scope="read")
            self.assertEqual(invoke.call_args.kwargs, {"authorized_scope": "read"})

    def test_batch_still_requires_authenticated_execute_scope(self):
        with patch("gway_remote.mcp_node_providers._node_registration",
                   side_effect=lambda registration: registration), \
             patch("gway_remote.mcp_node_providers.list_source_tools",
                   return_value=[READ, BATCH]), \
             patch("gway_remote.mcp_node_providers.call_source_tool") as invoke:
            with self.assertRaises(NodeProviderError) as context:
                provider_call([REG], provider="odoo",
                              tool="customer_vehicle_batch_apply",
                              arguments={"batch": {"schema_version": 1, "cases": []}},
                              authorized_scope="read")
            self.assertEqual(context.exception.code, "permission_denied")
            invoke.assert_not_called()

    def test_timeout_not_granted_to_other_provider_with_same_tool_name(self):
        other = replace(REG, source_id="other")
        with patch("gway_remote.mcp_node_providers._node_registration",
                   side_effect=lambda registration: registration), \
             patch("gway_remote.mcp_node_providers.list_source_tools",
                   return_value=[BATCH]), \
             patch("gway_remote.mcp_node_providers.call_source_tool",
                   return_value={"content": []}) as invoke:
            provider_call([other], provider="other", tool="customer_vehicle_batch_apply",
                          arguments={"batch": {"schema_version": 1, "cases": []}},
                          authorized_scope="execute")
            self.assertEqual(invoke.call_args.kwargs, {"authorized_scope": "execute"})


if __name__ == "__main__":
    unittest.main()
