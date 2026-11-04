"""End-to-end HTTP authorization boundary, with no real remote SSH execution."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import make_server


class GatewayExecuteHTTPTests(unittest.TestCase):
    def test_only_execute_scope_can_dispatch_without_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = BearerRegistry(Path(directory) / "credentials.db")
            read_token = registry.issue()
            parent = registry.issue(scope="gway:execute", operator_approved=True)
            execute_token = registry.issue(scope="gway:execute", parent_id=parent.split("_", 2)[1])
            mock_execution = Mock()
            mock_execution.exec.return_value = {
                "node": "gway-001", "request_id": "a"*32, "status": "dispatched"}
            with make_server(("127.0.0.1", 0), BearerVerifier(registry.path),
                             "http://127.0.0.1:19011/mcp", "backend-secret",
                             execution=mock_execution) as gateway:
                thread = threading.Thread(target=gateway.serve_forever, daemon=True)
                thread.start()
                try:
                    endpoint = "http://127.0.0.1:%d/mcp" % gateway.server_port
                    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "node_exec", "arguments": {
                            "node": "gway-001", "command": "uptime", "request_id": "a"*32}}}).encode()
                    def call(token):
                        request = Request(endpoint, body, {
                            "Authorization": "Bearer " + token,
                            "Content-Type": "application/json"}, method="POST")
                        try:
                            with urlopen(request, timeout=3) as response:
                                return response.status, json.loads(response.read())
                        except HTTPError as exc:
                            code = exc.code
                            exc.close()
                            return code, None
                    self.assertEqual(call(read_token)[0], 401)
                    mock_execution.exec.assert_not_called()
                    code, result = call(execute_token)
                    self.assertEqual(code, 200)
                    self.assertEqual(result["result"]["content"][0]["type"], "text")
                    mock_execution.exec.assert_called_once_with(
                        principal=parent.split("_", 2)[1],
                        node="gway-001", command="uptime", request_id="a"*32)
                    self.assertTrue(registry.revoke(parent.split("_", 2)[1]))
                    self.assertEqual(call(execute_token)[0], 401)
                finally:
                    gateway.shutdown()
                    thread.join()


if __name__ == "__main__":
    unittest.main()
