"""End-to-end HTTP authorization boundary, with no real remote SSH execution."""
from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tests.helpers.mcp_http import mcp_call, bearer_post
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
                    body = mcp_call('node_exec', {'node': 'gway-001',
                        'command': 'uptime', 'request_id': 'a' * 32})
                    def call(token):
                        request = bearer_post(endpoint, body, token)
                        try:
                            with urlopen(request, timeout=3) as response:
                                return response.status, json.loads(response.read())
                        except HTTPError as exc:
                            code = exc.code
                            exc.close()
                            return code, None
                    denied_status, denied = call(read_token)
                    self.assertEqual(denied_status, 200)
                    self.assertTrue(denied["result"]["isError"])
                    self.assertIn("mcp/www_authenticate", denied["result"]["_meta"])
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



class GatewayFederationRoutesHTTPTests(unittest.TestCase):
    def test_public_oauth_and_one_federated_discovery_per_call(self):
        """Loopback only: no SSH, remote provider, or real deployment."""
        from gway_remote.mcp_gateway_federation import FederatedProviders
        from tests.helpers.mcp_provider import provider_reply
        from tests.helpers.mcp_federation import fixture_tool

        class LocalTransport:
            def __init__(self):
                self.calls = []

            def invoke(self, node, request, *, trusted_scope):
                self.calls.append((node, dict(request), trusted_scope))
                if request["operation"] == "provider_list":
                    return provider_reply(
                        node, tools=[fixture_tool("lookup", read=True),
                                     fixture_tool("update")])
                if request["operation"] == "provider_call":
                    return {"content": []}
                raise AssertionError("Unexpected operation")

        with tempfile.TemporaryDirectory() as directory:
            registry = BearerRegistry(Path(directory) / "gateway.db")
            read_token = registry.issue()
            parent = registry.issue(scope="gway:execute", operator_approved=True)
            execute_token = registry.issue(
                scope="gway:execute", parent_id=parent.split("_", 2)[1])
            transport = LocalTransport()
            federation = FederatedProviders(
                transport=transport, nodes=lambda: ("gway-001",))
            with make_server(
                ("127.0.0.1", 0), BearerVerifier(registry.path),
                "http://127.0.0.1:19011/mcp", "backend-secret",
                federation=federation,
            ) as gateway:
                thread = threading.Thread(target=gateway.serve_forever,
                                          daemon=True)
                thread.start()
                try:
                    endpoint = "http://127.0.0.1:%d/mcp" % gateway.server_port

                    def call(name, token):
                        request = bearer_post(endpoint, mcp_call(name), token)
                        try:
                            with urlopen(request, timeout=3) as response:
                                return response.status
                        except HTTPError as exc:
                            status = exc.code
                            exc.close()
                            return status

                    self.assertEqual(call("odoo__lookup", None), 401)
                    self.assertEqual(len(transport.calls), 0)

                    self.assertEqual(call("odoo__lookup", read_token), 200)
                    self.assertEqual(
                        [x[1]["operation"] for x in transport.calls],
                        ["provider_list", "provider_call"])
                    self.assertEqual(transport.calls[-1][2], "read")

                    self.assertEqual(call("odoo__update", read_token), 401)
                    self.assertEqual(
                        [x[1]["operation"] for x in transport.calls],
                        ["provider_list", "provider_call", "provider_list"])

                    self.assertEqual(call("odoo__update", execute_token), 200)
                    self.assertEqual(
                        [x[1]["operation"] for x in transport.calls],
                        ["provider_list", "provider_call", "provider_list",
                         "provider_list", "provider_call"])
                    self.assertEqual(transport.calls[-1][2], "execute")

                    self.assertEqual(call("odoo__missing", execute_token), 403)
                    self.assertEqual(transport.calls[-1][1]["operation"],
                                     "provider_list")
                finally:
                    gateway.shutdown()
                    thread.join()


if __name__ == "__main__":
    unittest.main()
