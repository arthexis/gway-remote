"""Correlation is observational, not a new OAuth or execution boundary."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import unittest
from contextlib import redirect_stderr
from io import StringIO

from gway_remote.agentops_invocation_trace import ingress, current_id
from gway_remote.mcp_provider_transport import ProviderTransport
from gway_remote.node_exec_protocol import serve_one
from gway_remote.mcp_node_providers import provider_call
from gway_remote.mcp_source_registry import SourceRegistration
from gway_remote.mcp_source_stdio import call_source_tool

NODE = "gway-001"
RID = "a"*32
PRINCIPAL = "b"*24
REQUEST = {"operation": "provider_call", "provider": "agentops", "tool": "submit",
           "arguments": {"ref": "arthexis/example#1", "at": "2026-11-27T01:00:00Z"}}


class AgentOpsInvocationTraceTests(unittest.TestCase):
    def test_ingress_propagates_same_id_without_logging_credentials(self):
        captured = StringIO()
        redirect = redirect_stderr(captured)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        registry = Mock()
        registry.federated_principal.return_value = PRINCIPAL
        def invoke(payload):
            assert payload["request_id"] == current_id() == RID
            assert payload["arguments"] == REQUEST["arguments"]
            return {"node": NODE, "request_id": RID, "result": {"content": []}}
        transport = Mock()
        transport.invoke.side_effect = invoke
        with patch("gway_remote.agentops_invocation_trace.secrets.token_hex", return_value=RID), \
             patch("gway_remote.mcp_provider_transport.pinned_transport", return_value=transport):
            with ingress("agentops", registry=registry, credential="secret-bearer",
                         scope="execute", rpc_id="client-private-id"):
                assert ProviderTransport(Mock()).invoke(NODE, REQUEST, trusted_scope="execute") == {"content": []}
        assert current_id() is None
        logs = captured.getvalue()
        assert "secret-bearer" not in logs and "client-private-id" not in logs
        assert "arthexis/example" not in logs
        rows = [json.loads(line) for line in logs.splitlines()]
        assert [r["stage"] for r in rows] == ["ingress", "transport", "returned"]
        assert {r["trace_id"] for r in rows} == {RID}
        assert rows[0]["principal"] == PRINCIPAL
        assert len(rows[0]["client_rpc_id_sha256"]) == 64


    def test_unrelated_response_fails_closed(self):
        captured = StringIO()
        redirect = redirect_stderr(captured)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        registry = Mock()
        registry.federated_principal.return_value = PRINCIPAL
        transport = Mock()
        transport.invoke.return_value = {"node": NODE, "request_id": "c"*32, "result": {}}
        with patch("gway_remote.agentops_invocation_trace.secrets.token_hex", return_value=RID), \
             patch("gway_remote.mcp_provider_transport.pinned_transport", return_value=transport):
            with ingress("agentops", registry=registry, credential="secret", scope="execute", rpc_id=1):
                with self.assertRaises(ValueError):
                    ProviderTransport(Mock()).invoke(NODE, REQUEST, trusted_scope="execute")
        assert json.loads(captured.getvalue().splitlines()[-1])["stage"] == "uncertain"


    def test_agentops_receiver_passes_trusted_envelope_id_to_provider(self):
        payload = {**REQUEST, "node": NODE, "request_id": RID}
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.mcp_installed_providers.discover_installed_providers", return_value=[]), \
             patch("gway_remote.mcp_node_providers.dispatch_node_provider_request", return_value={"content":[]}) as dispatch:
            response = serve_one(json.dumps(payload).encode(), hostname=NODE, trusted_relay=True)
        assert response["request_id"] == RID
        assert dispatch.call_args.kwargs["invocation_id"] == RID


    def test_node_passes_id_to_stdio_without_changing_scope(self):
        reg = SourceRegistration("agentops", "a"*40, "/tmp/provider", ("/tmp/provider",), "arthe", True)
        tool = {"name": "submit", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": False}}
        with patch("gway_remote.mcp_node_providers._node_registration", return_value=reg), \
             patch("gway_remote.mcp_node_providers.list_source_tools", return_value=[tool]), \
             patch("gway_remote.mcp_node_providers.call_source_tool", return_value={"content":[]}) as call:
            with self.assertRaises(RuntimeError):
                provider_call([reg], provider="agentops", tool="submit", arguments={}, authorized_scope="read", invocation_id=RID)
            call.assert_not_called()
            provider_call([reg], provider="agentops", tool="submit", arguments={}, authorized_scope="execute", invocation_id=RID)
            assert call.call_args.kwargs["invocation_id"] == RID
            assert call.call_args.kwargs["authorized_scope"] == "execute"


    def test_stdio_uses_id_and_not_tool_arguments(self):
        reg = SourceRegistration("agentops", "a"*40, "/tmp/provider", ("/tmp/provider",), "arthe", True)
        tool = {"name": "status", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}
        session = Mock()
        session.request.side_effect = [{"tools": [tool]}, {"content": []}]
        manager = Mock()
        manager.__enter__ = Mock(return_value=session)
        manager.__exit__ = Mock(return_value=False)
        with patch("gway_remote.mcp_source_stdio._Session", return_value=manager):
            assert call_source_tool(reg, "status", {}, tool, authorized_scope="read", invocation_id=RID) == {"content":[]}
        assert session.request.call_args.args == (RID, "tools/call", {"name": "status", "arguments": {}})
