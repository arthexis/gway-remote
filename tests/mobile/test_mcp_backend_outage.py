"""Gateway-owned MCP discovery survives loss of the gway-001 backend.

All tests use loopback servers; no WireGuard, real nodes, or credentials.
"""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import make_server
from tests.helpers.mcp_http import bearer_post


class IndependentFederation:
    def discover(self, builtins=()):
        return list(builtins), {}


class HealthyBackend(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        response = {"jsonrpc": "2.0", "id": 1,
                    "result": {"tools": [
                        {"name": "mcp_source_status",
                         "inputSchema": {"type": "object"},
                         "annotations": {"readOnlyHint": True}}]}}
        data = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class BackendOutageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        registry = BearerRegistry(Path(self.temp.name) / "bearers.sqlite3")
        self.token = registry.issue()
        self.gateway = make_server(
            ("127.0.0.1", 0), BearerVerifier(registry.path),
            "http://127.0.0.1:1/mcp", "independent-backend-token",
            federation=IndependentFederation())
        self.addCleanup(self.gateway.server_close)
        worker = threading.Thread(target=self.gateway.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(self.gateway.shutdown)

    def call(self, method, *, params=None, token=None, version="2025-03-26", notification=False):
        request = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notification:
            request["id"] = 19
        if version == "2026-07-28":
            request["params"]["_meta"] = {
                "io.modelcontextprotocol/protocolVersion": version}
        body = json.dumps(request).encode()
        url = "http://127.0.0.1:%s/mcp" % self.gateway.server_port
        req = bearer_post(url, body, self.token if token is None else token)
        req.add_header("MCP-Protocol-Version", version)
        try:
            with urlopen(req, timeout=8) as reply:
                return reply.status, json.loads(reply.read()) if not notification else None
        except HTTPError as exc:
            status = exc.code
            exc.close()
            return status, None

    def test_fallback_initialize_list_and_modern_protocol(self):
        for version in ("2025-03-26", "2026-07-28"):
            with self.subTest(version=version):
                status, init = self.call("initialize", version=version,
                                         params={"protocolVersion": version})
                self.assertEqual(status, 200)
                self.assertEqual(init["result"]["protocolVersion"], "2025-03-26")
                status, listed = self.call("tools/list", version=version)
                self.assertEqual(status, 200)
                result = listed["result"]
                if version == "2026-07-28":
                    self.assertEqual(result["resultType"], "complete")
                names = {entry["name"] for entry in result["tools"]}
                self.assertIn("node_list", names)
                self.assertIn("node_capabilities", names)
                self.assertNotIn("github_workflow_runs", names)
                self.assertNotIn("mcp_source_status", names)
                self.assertTrue(all(t["securitySchemes"][0]["scopes"] == ["gway:read"]
                                    for t in result["tools"]))

    def test_catalog_inspection_matches_fallback_tools(self):
        status, listed = self.call("tools/list")
        self.assertEqual(status, 200)
        status, inspected = self.call("tools/call",
            params={"name": "mcp_catalog_inspect", "arguments": {}})
        self.assertEqual(status, 200)
        projection = json.loads(inspected["result"]["content"][0]["text"])
        self.assertEqual({t["name"] for t in listed["result"]["tools"]},
                         {t["name"] for t in projection["tools"]})

    def test_notifications_auth_errors_and_no_backend_execution(self):
        self.assertEqual(self.call("notifications/initialized", notification=True)[0], 202)
        self.assertEqual(self.call("tools/list", token="not-a-token")[0], 401)
        self.assertEqual(self.call("tools/list", params={"unexpected": 1})[0], 400)
        self.assertEqual(self.call("initialize", params={"protocolVersion": 3})[0], 400)
        self.assertEqual(self.call("tools/call",
            params={"name": "agent_submit", "arguments": {}})[0], 403)
        # Retired GitHub builtins cannot reach a private backend, even when down.
        self.assertEqual(self.call("tools/call",
            params={"name": "github_workflow_runs", "arguments": {}})[0], 403)
        # Source diagnostics is gateway-owned and remains available offline.
        self.assertEqual(self.call("tools/call",
            params={"name": "mcp_source_status", "arguments": {}})[0], 200)

    def test_backend_http_denial_does_not_trigger_fallback(self):
        from unittest.mock import Mock
        denied = HTTPError("http://127.0.0.1:1/mcp", 401, "denied", {}, None)
        self.gateway.opener.open = Mock(side_effect=denied)
        self.assertEqual(self.call("tools/list")[0], 502)

    def test_recovery_restores_backend_catalog_without_cache(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), HealthyBackend) as backend:
            worker = threading.Thread(target=backend.serve_forever, daemon=True)
            worker.start()
            try:
                self.gateway.upstream = "http://127.0.0.1:%s/mcp" % backend.server_port
                status, listed = self.call("tools/list")
                self.assertEqual(status, 200)
                self.assertIn("mcp_source_status",
                    {entry["name"] for entry in listed["result"]["tools"]})
            finally:
                backend.shutdown()
                worker.join()


if __name__ == "__main__":
    unittest.main()
