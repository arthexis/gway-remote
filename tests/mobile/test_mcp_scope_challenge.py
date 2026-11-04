"""Per-tool OAuth scope challenge over the real gateway HTTP boundary."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import make_server, EXEC_TOOLS, NODE_TOOLS, scoped_tool, EXEC_SECURITY, READ_SECURITY


class ExecuteScopeChallengeTests(unittest.TestCase):
    def test_tool_schemes_annotate_read_and_execute_separately(self):
        self.assertEqual({item["name"] for item in EXEC_TOOLS},
                         {"node_exec", "node_result", "node_cancel",
                          "node_deploy", "node_deploy_status"})
        for tool in EXEC_TOOLS:
            self.assertEqual(scoped_tool(tool, EXEC_SECURITY)["securitySchemes"],
                             [{"type": "oauth2", "scopes": ["gway:execute"]}])
            self.assertEqual(tool["_meta"]["securitySchemes"],
                             [{"type": "oauth2", "scopes": ["gway:execute"]}])
        for tool in NODE_TOOLS:
            self.assertEqual(scoped_tool(tool, READ_SECURITY)["securitySchemes"],
                             [{"type": "oauth2", "scopes": ["gway:read"]}])
            self.assertEqual(tool["_meta"]["securitySchemes"],
                             [{"type": "oauth2", "scopes": ["gway:read"]}])

    def test_initial_connection_requests_execute_and_read_only_still_available(self):
        with tempfile.TemporaryDirectory() as home:
            registry = BearerRegistry(Path(home) / "tokens.db")
            read_token = registry.issue()
            exec_token = registry.issue(scope="gway:execute", operator_approved=True)
            with make_server(("127.0.0.1", 0), BearerVerifier(registry.path),
                             "http://127.0.0.1:19011/mcp", "backend-secret") as gateway:
                thread = threading.Thread(target=gateway.serve_forever, daemon=True)
                thread.start()
                try:
                    endpoint = "http://127.0.0.1:%d/mcp" % gateway.server_port
                    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                       "params": {"name": "node_list", "arguments": {}}}).encode()
                    def send(token=None):
                        headers = {"Content-Type": "application/json"}
                        if token is not None:
                            headers["Authorization"] = "Bearer " + token
                        return Request(endpoint, body, headers, method="POST")
                    with self.assertRaises(HTTPError) as missing:
                        urlopen(send(), timeout=3)
                    self.assertEqual(missing.exception.code, 401)
                    self.assertIn('scope="gway:execute"',
                                  missing.exception.headers["WWW-Authenticate"])
                    self.assertNotIn("insufficient_scope",
                                     missing.exception.headers["WWW-Authenticate"])
                    missing.exception.close()
                    # An operator's one execute credential works for all read
                    # operations; explicit read-only clients are unaffected.
                    for token in (read_token, exec_token):
                        with urlopen(send(token), timeout=3) as res:
                            self.assertEqual(res.status, 200)
                finally:
                    gateway.shutdown()
                    thread.join(timeout=3)

    def test_read_bearer_receives_execute_scope_challenge_without_dispatch(self):
        with tempfile.TemporaryDirectory() as home:
            registry = BearerRegistry(Path(home) / "tokens.db")
            read_token = registry.issue()
            execute_token = registry.issue(scope="gway:execute", operator_approved=True)
            executor = Mock()
            executor.exec.return_value = {"request_id": "a" * 32, "node": "gway-001", "status": "dispatched"}
            with make_server(("127.0.0.1", 0), BearerVerifier(registry.path),
                             "http://127.0.0.1:19011/mcp", "backend-secret",
                             execution=executor) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    url = "http://127.0.0.1:%d/mcp" % server.server_port
                    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "node_exec", "arguments": {
                            "node": "gway-001", "command": "hostname", "request_id": "a" * 32}}}).encode()
                    def request(token):
                        return Request(url, payload, {"Authorization": "Bearer " + token,
                                     "Content-Type": "application/json"}, method="POST")
                    with urlopen(request(read_token), timeout=3) as denied:
                        self.assertEqual(denied.status, 200)
                        reply = json.loads(denied.read())
                    self.assertTrue(reply["result"]["isError"])
                    self.assertEqual(reply["id"], 1)
                    challenge = reply["result"]["_meta"]["mcp/www_authenticate"][0]
                    self.assertIn('scope="gway:execute"', challenge)
                    self.assertIn('error="insufficient_scope"', challenge)
                    self.assertNotIn(read_token, json.dumps(reply))
                    executor.exec.assert_not_called()
                    with urlopen(request(execute_token), timeout=3) as accepted:
                        self.assertEqual(accepted.status, 200)
                    executor.exec.assert_called_once()
                finally:
                    server.shutdown()
                    thread.join(timeout=3)
