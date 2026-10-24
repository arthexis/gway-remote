"""MCP transport contract: no execution, no public bind, fail-closed auth."""
import json
import os
import threading
import unittest
from http.client import HTTPConnection
from unittest.mock import patch
from gway_remote import mcp_http


class MCPTransportTests(unittest.TestCase):
    def test_methods(self):
        result, error, _ = mcp_http.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertIsNone(error)
        self.assertEqual(len(result["tools"]), 4)
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in result["tools"]))
        _, error, _ = mcp_http.handle({"jsonrpc": "2.0", "id": 2, "method": "agent_submit"})
        self.assertEqual(error, -32601)

    def test_dispatch_denied(self):
        result, code, _ = mcp_http.handle({"jsonrpc": "2.0", "id": 2,
              "method": "tools/call", "params": {"name": "agent_submit", "arguments": {}}})
        self.assertIsNone(result)
        self.assertEqual(code, -32602)

    def test_bind_restriction(self):
        with self.assertRaises(ValueError):
            mcp_http.serve("0.0.0.0", 8770)

    def test_requires_secret(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            mcp_http.serve()

    def test_http_auth_and_no_origin(self):
        with patch.dict(os.environ, {"GWAY_MCP_BEARER_TOKEN": "test-secret"}):
            server = mcp_http.ThreadingHTTPServer(("127.0.0.1", 0), mcp_http.Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                def request(headers):
                    conn = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                    conn.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
                                 headers=headers)
                    response = conn.getresponse()
                    status = response.status
                    data = response.read()
                    conn.close()
                    return status, data
                self.assertEqual(request({})[0], 401)
                self.assertEqual(request({"Authorization": "Bearer wrong"})[0], 401)
                self.assertEqual(request({"Authorization": "Bearer test-secret", "Origin": "https://bad.example"})[0], 403)
                status, body = request({"Authorization": "Bearer test-secret"})
                self.assertEqual(status, 200)
                self.assertIn(b"agent_list_issues", body)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
