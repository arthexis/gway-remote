"""Read-only Watchtower-local node tools over authenticated MCP gateway."""
import json
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import make_server


class LegacyBackend(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        if request["method"] == "tools/list":
            result = {"tools": [
                {"name": name, "inputSchema": {"type": "object", "properties": {}},
                 "annotations": {"readOnlyHint": True}}
                for name in ("agent_status", "agent_list_issues", "agent_preview",
                             "agent_observe", "github_workflow_runs",
                             "github_workflow_status", "github_workflow_errors")
            ]}
        else:
            result = {"content": [{"type": "text", "text": "unrelated"}]}
        body = json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GatewayNodeInventoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        registry = BearerRegistry(Path(temp.name) / "tokens.sqlite")
        self.token = registry.issue()
        self.backend = ThreadingHTTPServer(("127.0.0.1", 0), LegacyBackend)
        self.addCleanup(self.backend.server_close)
        t1 = threading.Thread(target=self.backend.serve_forever, daemon=True)
        t1.start()
        self.addCleanup(t1.join)
        self.addCleanup(self.backend.shutdown)
        self.gateway = make_server(
            ("127.0.0.1", 0), BearerVerifier(registry.path),
            f"http://127.0.0.1:{self.backend.server_port}/mcp", "private-backend-secret")
        self.addCleanup(self.gateway.server_close)
        t2 = threading.Thread(target=self.gateway.serve_forever, daemon=True)
        t2.start()
        self.addCleanup(t2.join)
        self.addCleanup(self.gateway.shutdown)
        self.snapshot = {"schema": 1, "source": "watchtower-enrollment-ledger",
                         "generated_at": "2026-11-03T00:00:00+00:00",
                         "nodes": [
                             {"node": "gway-001", "registered": True,
                              "identity_verified": True, "reachable": "unknown",
                              "observed_at": None, "execute_available": False,
                              "address": "10.90.0.2"},
                         ]}
        patcher = patch("gway_remote.node_registry_inventory.load", return_value=self.snapshot)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rpc(self, method, params=None, token=True, version="2025-03-26"):
        headers = {"Content-Type": "application/json",
                   "MCP-Protocol-Version": version}
        if token:
            headers["Authorization"] = "Bearer " + self.token
        if version == "2026-07-28":
            params = {**(params or {}), "_meta": {
                "io.modelcontextprotocol/protocolVersion": version}}
        request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        conn = HTTPConnection("127.0.0.1", self.gateway.server_port, timeout=4)
        try:
            conn.request("POST", "/mcp", json.dumps(request), headers)
            res = conn.getresponse()
            return res.status, json.loads(res.read() or b"{}")
        finally:
            conn.close()

    def test_tools_list_adds_preview_without_changing_legacy_tools(self):
        for version in ("2025-03-26", "2026-07-28"):
            with self.subTest(version=version):
                status, result = self.rpc("tools/list", version=version)
                self.assertEqual(status, 200)
                tools = result["result"]["tools"]
                self.assertEqual(len(tools), 11)
                self.assertEqual({x["name"] for x in tools[-4:]},
                                 {"node_list", "node_capabilities", "node_exec_preview", "node_deploy_preview"})
                self.assertTrue(all(x["annotations"]["readOnlyHint"] for x in tools))
                self.assertNotIn("agent_submit", {x["name"] for x in tools})

    def test_node_list_excludes_private_ip_and_never_claims_reachability(self):
        status, response = self.rpc("tools/call",
                                    {"name": "node_list", "arguments": {}})
        self.assertEqual(status, 200)
        result = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(result["nodes"][0]["node"], "gway-001")
        self.assertNotIn("10.90.0.2", json.dumps(result))
        self.assertEqual(result["nodes"][0]["reachable"], "unknown")
        self.assertEqual(result["nodes"][0]["execution_health"], "unverified")
        self.assertIs(result["nodes"][0]["execute_available"], False)

    def test_capability_and_unknown_node_fail_closed(self):
        status, response = self.rpc("tools/call",
                                    {"name": "node_capabilities",
                                     "arguments": {"node": "gway-001"}},
                                    version="2026-07-28")
        self.assertEqual(status, 200)
        self.assertEqual(response["result"]["resultType"], "complete")
        self.assertFalse(json.loads(response["result"]["content"][0]["text"])["execute_available"])
        self.assertEqual(json.loads(response["result"]["content"][0]["text"])["execution_health"], "unverified")
        status, response = self.rpc("tools/call",
                                    {"name": "node_capabilities",
                                     "arguments": {"node": "unknown-host"}})
        self.assertEqual(status, 200)
        self.assertTrue(response["result"]["isError"])

    def test_preview_is_read_only_and_requires_attested_identity(self):
        status, response = self.rpc("tools/call", {"name": "node_exec_preview",
            "arguments": {"node": "gway-001", "command": "df -h && uptime"}})
        self.assertEqual(status, 200)
        preview = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(preview["command"], "df -h && uptime")
        self.assertEqual(preview["status"], "preview_only")
        self.assertFalse(preview["execute_available"])
        status, response = self.rpc("tools/call", {"name": "node_exec_preview",
            "arguments": {"node": "gway-002", "command": "uptime"}})
        self.assertEqual(status, 200)
        self.assertTrue(response["result"]["isError"])

    def test_unauthorized_and_forbidden_exec_never_reach_runner(self):
        self.assertEqual(self.rpc("tools/list", token=False)[0], 401)
        status, denied = self.rpc("tools/call", {"name": "node_exec", "arguments": {
            "node": "gway-001", "command": "id"}})
        self.assertEqual(status, 200)
        self.assertTrue(denied["result"]["isError"])
        self.assertIn("mcp/www_authenticate", denied["result"]["_meta"])
        self.assertEqual(self.rpc("tools/call", {"name": "agent_submit"})[0], 403)


if __name__ == "__main__":
    unittest.main()
