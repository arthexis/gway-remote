"""2026 MCP action discovery over existing 2025 backend without modifying field agents."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

from gway_remote import mcp_http
from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import make_server

MODERN = "2026-07-28"
LEGACY = "2025-03-26"


class ModernDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = BearerRegistry(Path(self.temp.name) / "registry.sqlite")
        self.token = self.registry.issue()
        self.backend_token = "backend-only-secret"
        self.env = patch.dict(os.environ, {"GWAY_MCP_BEARER_TOKEN": self.backend_token})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.backend = mcp_http.ThreadingHTTPServer(("127.0.0.1", 0), mcp_http.Handler)
        self.addCleanup(self.backend.server_close)
        self.worker = threading.Thread(target=self.backend.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.worker.join)
        self.addCleanup(self.backend.shutdown)
        self.gateway = make_server(("127.0.0.1", 0), BearerVerifier(self.registry.path),
                                   f"http://127.0.0.1:{self.backend.server_port}/mcp",
                                   self.backend_token)
        self.addCleanup(self.gateway.server_close)
        self.gateway_worker = threading.Thread(target=self.gateway.serve_forever, daemon=True)
        self.gateway_worker.start()
        self.addCleanup(self.gateway_worker.join)
        self.addCleanup(self.gateway.shutdown)

    def rpc(self, method, version=MODERN, bearer=True, params=None):
        if params is None:
            params = {}
        if version == MODERN:
            params["_meta"] = {"io.modelcontextprotocol/protocolVersion": MODERN,
                                "io.modelcontextprotocol/clientInfo":
                                {"name": "chatgpt-client", "version": "1.0.0"},
                                "io.modelcontextprotocol/clientCapabilities": {}}
        request = {"jsonrpc": "2.0", "id": 23, "method": method, "params": params}
        conn = HTTPConnection("127.0.0.1", self.gateway.server_port, timeout=3)
        try:
            headers = {"Content-Type": "application/json", "MCP-Protocol-Version": version,
                       "Accept": "application/json, text/event-stream"}
            if bearer:
                headers["Authorization"] = "Bearer " + self.token
            conn.request("POST", "/mcp", json.dumps(request), headers)
            result = conn.getresponse()
            return result.status, dict(result.getheaders()), result.read()
        finally:
            conn.close()

    def test_modern_server_discover_returns_supported_versions_and_capability(self):
        status, headers, body = self.rpc("server/discover")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("MCP-Protocol-Version"), MODERN)
        result = json.loads(body)["result"]
        self.assertEqual(result["resultType"], "complete")
        self.assertEqual(result["supportedVersions"][0], MODERN)
        self.assertEqual(result["capabilities"], {"tools": {}})
        self.assertEqual(result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "gway-agent-ops")

    def test_modern_tools_list_has_result_type_and_seven_read_only_tools(self):
        status, headers, body = self.rpc("tools/list")
        self.assertEqual(status, 200)
        result = json.loads(body)["result"]
        self.assertEqual(result["resultType"], "complete")
        self.assertIn("mcp_source_status", {tool["name"] for tool in result["tools"]})
        self.assertEqual(len({tool["name"] for tool in result["tools"]}), len(result["tools"]))
        self.assertEqual({x["name"] for x in result["tools"][-6:]},
                         {"node_list", "fleet_snapshot", "node_capabilities", "node_exec_preview", "node_deploy_preview", "workspace_inspect"})
        self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in result["tools"] if tool["name"] != "agent_submit"))
        self.assertNotIn("agent_submit", {tool["name"] for tool in result["tools"]})

    def test_legacy_initialize_still_negotiates_exact_version(self):
        status, _, body = self.rpc("initialize", LEGACY,
                                   params={"protocolVersion": "2025-11-25",
                                           "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["result"]["protocolVersion"], LEGACY)

    def test_unauthenticated_discovery_denied_and_unknown_tool_disallowed(self):
        status, _, _ = self.rpc("server/discover", bearer=False)
        self.assertEqual(status, 401)
        status, _, _ = self.rpc("tools/call", params={"name": "agent_submit", "arguments": {}})
        self.assertEqual(status, 403)

    def test_modern_metadata_version_mismatch_is_denied(self):
        payload = {"jsonrpc": "2.0", "id": 23, "method": "tools/list",
                   "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": LEGACY}}}
        connection = HTTPConnection("127.0.0.1", self.gateway.server_port, timeout=3)
        try:
            connection.request("POST", "/mcp", json.dumps(payload),
                               {"Authorization": "Bearer " + self.token,
                                "Content-Type": "application/json",
                                "MCP-Protocol-Version": MODERN})
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
