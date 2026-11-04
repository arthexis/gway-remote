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
from gway_remote.mcp_bearer_gateway import make_server, EXEC_TOOLS, NODE_TOOLS


class ExecuteScopeChallengeTests(unittest.TestCase):
    def test_tool_schemes_annotate_read_and_execute_separately(self):
        self.assertEqual({item["name"] for item in EXEC_TOOLS},
                         {"node_exec", "node_result", "node_cancel"})
        for tool in EXEC_TOOLS:
            self.assertEqual(tool["_meta"]["securitySchemes"],
                             [{"type": "oauth2", "scopes": ["gway:execute"]}])
        for tool in NODE_TOOLS:
            self.assertEqual(tool["_meta"]["securitySchemes"],
                             [{"type": "oauth2", "scopes": ["gway:read"]}])

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
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(request(read_token), timeout=3)
                    self.assertEqual(denied.exception.code, 401)
                    challenge = denied.exception.headers["WWW-Authenticate"]
                    self.assertIn('scope="gway:execute"', challenge)
                    self.assertIn('error="insufficient_scope"', challenge)
                    denied.exception.close()
                    executor.exec.assert_not_called()
                    with urlopen(request(execute_token), timeout=3) as accepted:
                        self.assertEqual(accepted.status, 200)
                    executor.exec.assert_called_once()
                finally:
                    server.shutdown()
                    thread.join(timeout=3)
