"""Protocol and authorization regression tests for the read-only MCP transport."""
import json
import os
import threading
import unittest
from http.client import HTTPConnection
from unittest.mock import patch
from gway_remote import mcp_http


HEADERS = {
    "Authorization": "Bearer test-secret",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": mcp_http.PROTOCOL,
}


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

    def test_malformed_json_rpc_and_notifications(self):
        self.assertEqual(mcp_http.handle([])[1], -32600)
        self.assertEqual(mcp_http.handle({"jsonrpc": "2.0", "method": "initialize",
                          "params": {"protocolVersion": "2099-01-01"}})[1], -32602)
        self.assertEqual(mcp_http.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                         (None, None, None))
        self.assertEqual(mcp_http.handle({"jsonrpc": "2.0", "method": "notifications/unknown"}),
                         (None, None, None))
        self.assertEqual(mcp_http.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list",
                                           "params": {"unexpected": 1}})[1], -32602)

    def test_bind_restriction(self):
        with self.assertRaises(ValueError):
            mcp_http.serve("0.0.0.0", 8770)
        with self.assertRaises(ValueError):
            mcp_http.serve("::1", 8770)

    def test_requires_secret(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            mcp_http.serve()

    def test_http_headers_auth_and_origin(self):
        with patch.dict(os.environ, {"GWAY_MCP_BEARER_TOKEN": "test-secret"}):
            server = mcp_http.ThreadingHTTPServer(("127.0.0.1", 0), mcp_http.Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                def request(method="POST", headers=None, payload=None, path="/mcp"):
                    if payload is None:
                        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
                    conn = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                    conn.request(method, path, body=json.dumps(payload) if method == "POST" else None,
                                 headers=headers or {})
                    response = conn.getresponse()
                    status = response.status
                    data = response.read()
                    conn.close()
                    return status, data
                self.assertEqual(request(headers={})[0], 401)
                self.assertEqual(request(headers={**HEADERS, "Authorization": "Bearer wrong"})[0], 401)
                self.assertEqual(request(headers={**HEADERS, "Origin": "https://bad.example"})[0], 403)
                self.assertEqual(request(headers={**HEADERS, "Accept": "application/json"})[0], 406)
                self.assertEqual(request(headers={**HEADERS, "Content-Type": "text/plain"})[0], 415)
                self.assertEqual(request(headers={**HEADERS, "MCP-Protocol-Version": "2099-01-01"})[0], 400)
                self.assertEqual(request(headers=HEADERS, path="/api/v1/execute")[0], 404)
                self.assertEqual(request(method="GET", headers=HEADERS)[0], 405)
                self.assertEqual(request(headers=HEADERS, payload=[])[0], 400)
                self.assertEqual(request(headers=HEADERS,
                    payload={"jsonrpc": "2.0", "method": "notifications/initialized"})[0], 202)
                status, body = request(headers=HEADERS)
                self.assertEqual(status, 200)
                self.assertIn(b"agent_list_issues", body)
                status, body = request(headers=HEADERS,
                    payload={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                             "params": {"name": "agent_submit", "arguments": {}}})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["error"]["code"], -32602)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
