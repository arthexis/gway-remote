"""Fail-closed tests for bearer gate without opening a network port."""
import unittest
from gway_remote.mcp_bearer_gateway import inspect_rpc, make_server
from gway_remote.mcp_bearer import BearerRegistry
import tempfile
import json
from pathlib import Path

class GatewayTests(unittest.TestCase):
    def test_allowlist(self):
        for method in ("initialize", "tools/list", "notifications/initialized"):
            self.assertTrue(inspect_rpc(json.dumps({"jsonrpc":"2.0","method":method}).encode()))
        self.assertFalse(inspect_rpc(b"[]"))
        self.assertFalse(inspect_rpc(b"not json"))
        self.assertFalse(inspect_rpc(b'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"agent_submit"}}'))
        self.assertFalse(inspect_rpc(b'{"jsonrpc":"2.0","method":"execute"}'))
        self.assertTrue(inspect_rpc(b'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"agent_status"}}'))

    def test_private_endpoint_required(self):
        with tempfile.TemporaryDirectory() as d:
            registry = BearerRegistry(Path(d) / "secrets.db")
            for url in ("https://example.com/mcp", "http://0.0.0.0:1/mcp", "http://127.0.0.1:19011/other"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    make_server(("127.0.0.1", 0), registry, url, "separate")
            with self.assertRaises(ValueError):
                make_server(("127.0.0.1", 0), registry, "http://127.0.0.1:19011/mcp", "")

if __name__ == "__main__":
    unittest.main()
