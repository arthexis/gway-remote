import unittest
from unittest.mock import patch

from gway_remote.mcp_provider_protocol import serve_one
from gway_remote.mcp_gateway_federation import FederatedProviders


class ProviderWireTests(unittest.TestCase):
    def test_node_receiver_never_accepts_scope_from_request(self):
        request = b'{"node":"gway-001","request_id":"0123456789abcdef0123456789abcdef","scope":"execute","request":{"operation":"provider_list"}}'
        with patch("gway_remote.mcp_provider_protocol.os.geteuid", return_value=1000):
            with self.assertRaises(ValueError):
                serve_one(request, registrations=(), node_id="gway-001",
                          trusted_scope="read")

    def test_node_receiver_lists_local_sources(self):
        request = b'{"node":"gway-001","request_id":"0123456789abcdef0123456789abcdef","request":{"operation":"provider_list"}}'
        with patch("gway_remote.mcp_provider_protocol.os.geteuid", return_value=1000):
            response = serve_one(request, registrations=(), node_id="gway-001",
                                 trusted_scope="read")
        self.assertEqual(response["result"], {"node": "gway-001", "providers": []})

    def test_watchtower_never_reads_local_registry(self):
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
