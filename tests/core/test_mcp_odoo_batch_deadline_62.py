"""Issue arthexis/odoo-gelectriic#62: only the Odoo batch gets extra stdio time.

Hermetic scope and timeout checks; no Odoo, network or private data.
"""
from dataclasses import replace
from unittest.mock import patch

import pytest

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


def test_customer_batch_has_bounded_deadline_other_tools_keep_default():
    with patch("gway_remote.mcp_node_providers._node_registration",
               side_effect=lambda registration: registration), \
         patch("gway_remote.mcp_node_providers.list_source_tools",
               return_value=[READ, WRITE, BATCH]), \
         patch("gway_remote.mcp_node_providers.call_source_tool",
               return_value={"content": []}) as invoke:
        batch = {"batch": {"schema_version": 1, "cases": []}}
        assert provider_call([REG], provider="odoo",
                             tool="customer_vehicle_batch_apply", arguments=batch,
                             authorized_scope="execute") == {"content": []}
        assert invoke.call_args.kwargs == {"authorized_scope": "execute",
                                           "timeout": 25}
        provider_call([REG], provider="odoo", tool="customer_update",
                      arguments={"id": 1}, authorized_scope="execute")
        assert invoke.call_args.kwargs == {"authorized_scope": "execute"}
        provider_call([REG], provider="odoo", tool="customer_search",
                      arguments={"query": "synthetic"}, authorized_scope="read")
        assert invoke.call_args.kwargs == {"authorized_scope": "read"}


def test_batch_still_requires_authenticated_execute_scope():
    with patch("gway_remote.mcp_node_providers._node_registration",
               side_effect=lambda registration: registration), \
         patch("gway_remote.mcp_node_providers.list_source_tools",
               return_value=[READ, BATCH]), \
         patch("gway_remote.mcp_node_providers.call_source_tool") as invoke:
        with pytest.raises(NodeProviderError, match="permission_denied"):
            provider_call([REG], provider="odoo",
                          tool="customer_vehicle_batch_apply",
                          arguments={"batch": {"schema_version": 1, "cases": []}},
                          authorized_scope="read")
        invoke.assert_not_called()


def test_timeout_not_granted_to_other_provider_with_same_tool_name():
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
        assert invoke.call_args.kwargs == {"authorized_scope": "execute"}
