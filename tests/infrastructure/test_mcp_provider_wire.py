import unittest
from unittest.mock import patch

from gway_remote.node_exec_protocol import serve_one
from gway_remote.mcp_gateway_federation import FederatedProviders


class ProviderWireTests(unittest.TestCase):
    def test_node_receiver_lists_local_sources(self):
        request = b'{"operation":"provider_list","node":"gway-001","request_id":"0123456789abcdef0123456789abcdef"}'
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.node_exec_protocol.socket.gethostname", return_value="gway-001"), \
             patch("gway_remote.mcp_source_policy.policy_digest", return_value="a"*64), \
             patch("gway_remote.mcp_source_policy.load_source_policy", return_value=((), {})), \
             patch.dict("os.environ", {"GWAY_MCP_SOURCE_POLICY": "/etc/gway-mcp-gateway/sources.json"}):
            response = serve_one(request)
        self.assertEqual(response["result"], {"node": "gway-001", "providers": []})

    def test_watchtower_uses_node_transport(self):
        class Transport:
            def invoke(self, node, request, *, trusted_scope):
                self.last = (node, request, trusted_scope)
                return {"node": node, "providers": []}
        transport = Transport()
        tools, routes = FederatedProviders(
            transport=transport, nodes=lambda: ("gway-001",)).discover()
        self.assertEqual(tools, [])
        self.assertEqual(routes, {})
        self.assertEqual(transport.last[1], {"operation": "provider_list"})


if __name__ == "__main__":
    unittest.main()
