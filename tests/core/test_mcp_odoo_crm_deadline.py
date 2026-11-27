"""CRM-specific scope and deadline regression; no business or network I/O."""
from dataclasses import replace
from unittest.mock import patch
import pytest
from gway_remote.mcp_node_providers import NodeProviderError, provider_call
from gway_remote.mcp_federated_catalog import catalog_from_nodes, route_provider_call
from gway_remote.mcp_source_registry import SourceRegistration

READ = ["crm_stage_list", "crm_team_list", "crm_opportunity_get", "crm_opportunity_search"]
WRITE = ["crm_opportunity_create", "crm_opportunity_update", "crm_opportunity_stage_move"]
TOOLS = [{"name": n, "inputSchema": {"type": "object"},
          "annotations": {"readOnlyHint": n in READ}} for n in READ+WRITE]
REG = SourceRegistration("odoo", "a"*40, "/usr/bin/true",
                         ("/usr/bin/true",), "arthe", True)

@pytest.mark.parametrize("name", WRITE)
def test_crm_write_scope_and_bounded_deadline(name):
    with patch("gway_remote.mcp_node_providers._node_registration", side_effect=lambda r:r), \
         patch("gway_remote.mcp_node_providers.list_source_tools", return_value=TOOLS), \
         patch("gway_remote.mcp_node_providers.call_source_tool", return_value={"content":[]}) as invoke:
        with pytest.raises(NodeProviderError) as exc:
            provider_call([REG], provider="odoo", tool=name, arguments={}, authorized_scope="read")
        assert exc.value.code=="permission_denied"
        invoke.assert_not_called()
        provider_call([REG], provider="odoo", tool=name, arguments={}, authorized_scope="execute")
        assert invoke.call_args.kwargs=={"authorized_scope":"execute","timeout":28}
        other=replace(REG,source_id="other")
        provider_call([other],provider="other",tool=name,arguments={},authorized_scope="execute")
        assert invoke.call_args.kwargs=={"authorized_scope":"execute"}

def test_crm_read_route_and_write_denial():
    node="gway-001"
    _, routes=catalog_from_nodes([], {node:{"node":node,"providers":[
        {"provider":"odoo","node":node,"revision":"a"*40,"status":"available",
         "supports_provider_read":True,"tools":TOOLS}]}})
    calls=[]
    def invoke(node,request,**kw): calls.append((node,request,kw))
    for name in WRITE:
        with pytest.raises(PermissionError):
            route_provider_call(routes,"odoo__"+name,{},authorized_scope="read",invoke=invoke)
    assert not calls
    for name in READ:
        route_provider_call(routes,"odoo__"+name,{},authorized_scope="read",invoke=invoke)
        assert calls[-1][1]["operation"]=="provider_read"
        assert calls[-1][2]["trusted_scope"]=="read"
