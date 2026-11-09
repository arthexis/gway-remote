import unittest
from unittest.mock import patch

from gway_remote.node_exec_protocol import serve_one
from gway_remote.mcp_gateway_federation import FederatedProviders


class ProviderWireTests(unittest.TestCase):
    def test_node_receiver_lists_local_sources(self):
        request = b'{"operation":"provider_list","node":"gway-001","request_id":"0123456789abcdef0123456789abcdef"}'
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.node_exec_protocol.socket.gethostname", return_value="gway-001"), \
             patch("gway_remote.mcp_installed_providers.discover_installed_providers", return_value=[]), \
             patch("gway_remote.mcp_source_policy.policy_digest", return_value="a"*64), \
             patch("gway_remote.mcp_source_policy.load_source_policy", return_value=((), {})), \
             patch.dict("os.environ", {"GWAY_MCP_SOURCE_POLICY": "/etc/gway-mcp-gateway/sources.json"}):
            response = serve_one(request)
        self.assertEqual(response["result"], {"node": "gway-001", "providers": []})

    def test_read_operation_enforced_on_node_and_no_scope_override(self):
        import json
        request = {"operation": "provider_read_call", "node": "gway-001",
                   "request_id": "0123456789abcdef0123456789abcdef",
                   "provider": "diagnostics", "tool": "hardware", "arguments": {}}
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.node_exec_protocol.socket.gethostname", return_value="gway-001"), \
             patch("gway_remote.mcp_installed_providers.discover_installed_providers", return_value=[]), \
             patch("gway_remote.mcp_node_providers.dispatch_node_provider_request",
                   return_value={"schema": "gway-remote/hardware/v1"}) as dispatch:
            serve_one(json.dumps(request).encode())
            self.assertEqual(dispatch.call_args.kwargs["trusted_scope"], "read")
            request["authorized_scope"] = "execute"
            with self.assertRaises(ValueError):
                serve_one(json.dumps(request).encode())
            self.assertEqual(dispatch.call_count, 1)

    def test_provider_transport_maps_read_to_node_enforced_operation(self):
        from gway_remote.mcp_provider_transport import ProviderTransport
        from types import SimpleNamespace
        class Pinned:
            node = SimpleNamespace(node="gway-001")
            def __init__(self): self.calls = []
            def invoke(self, payload):
                self.calls.append(payload)
                return {"node": payload["node"], "request_id": payload["request_id"], "result": {"ok": True}}
        pinned = Pinned()
        provider = ProviderTransport(pinned)
        self.assertEqual(provider.invoke("gway-001", {
            "operation": "provider_call", "provider": "diagnostics",
            "tool": "hardware", "arguments": {}}, trusted_scope="read"), {"ok": True})
        self.assertEqual(pinned.calls[0]["operation"], "provider_read_call")
        self.assertNotIn("authorized_scope", pinned.calls[0])
        class WrongReply(Pinned):
            def invoke(self, payload):
                return {"node": "gway-002", "request_id": payload["request_id"],
                        "result": {"ok": True}}
        with self.assertRaises(ValueError):
            ProviderTransport(WrongReply()).invoke("gway-001", {
                "operation": "provider_call", "provider": "diagnostics",
                "tool": "hardware", "arguments": {}}, trusted_scope="read")
        class ReplayReply(Pinned):
            def invoke(self, payload):
                return {"node": payload["node"], "request_id": "0" * 32,
                        "result": {"ok": True}}
        with self.assertRaises(ValueError):
            ProviderTransport(ReplayReply()).invoke("gway-001", {
                "operation": "provider_call", "provider": "diagnostics",
                "tool": "hardware", "arguments": {}}, trusted_scope="read")

    def test_legacy_execute_wire_is_not_peer_bound(self):
        """Document residual risk: caller-controlled execute scope on same relay."""
        import json
        payload = {"operation": "provider_call", "node": "gway-001",
                   "request_id": "0123456789abcdef0123456789abcdef",
                   "provider": "odoo", "tool": "write", "arguments": {},
                   "authorized_scope": "execute"}
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.mcp_installed_providers.discover_installed_providers",
                   return_value=[]), \
             patch("gway_remote.mcp_node_providers.dispatch_node_provider_request",
                   return_value={"ok": True}) as dispatch:
            serve_one(json.dumps(payload).encode(), hostname="gway-001")
        self.assertEqual(dispatch.call_args.kwargs["trusted_scope"], "execute")
        # This test intentionally proves the gap, not an authorization success:
        # SSH forced-command credentials currently do not distinguish read/exec.

    def test_watchtower_uses_node_transport(self):
        from tests.helpers.mcp_provider import InvocationSpy
        transport = InvocationSpy(response={"node": "gway-001", "providers": []})
        tools, routes = FederatedProviders(
            transport=transport, nodes=lambda: ("gway-001",)).discover()
        self.assertEqual(tools, [])
        self.assertEqual(routes, {})
        self.assertEqual(transport.calls[0][1], {"operation": "provider_list"})


if __name__ == "__main__":
    unittest.main()
