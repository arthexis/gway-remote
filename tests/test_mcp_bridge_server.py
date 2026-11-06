import tempfile
import threading
import time
import unittest
from pathlib import Path

from gway_remote.mcp_bridge_server import serve_gateway_session
from gway_remote.mcp_bridge_transport import call_unix


class Verifier:
    active = True

    def verify(self, token, *, required_scope):
        return self.active and token == "gateway-token" and required_scope in (
            "gway:read", "gway:execute")

    def execution_principal(self, token):
        return "a" * 24


class Execution:
    def __init__(self):
        self.calls = []

    def exec(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "dispatched"}


class Inventory:
    def public_nodes(self, *, execution_enabled):
        return {"nodes": [], "execute_enabled": execution_enabled}


class GatewayBridgeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.verifier = Verifier()
        self.execution = Execution()
        self.key = b"secret" * 8

    def envelope(self, *, operation="inventory.list", scope="gway:read",
                 principal="reader", arguments=None, nonce="b"):
        now = int(time.time())
        return {
            "version": 1, "request_id": nonce * 32,
            "principal": principal, "audience": "gway-001",
            "operation": operation, "scope": scope,
            "issued_at": now, "expires_at": now + 30,
            "arguments": {} if arguments is None else arguments,
        }

    def test_socket_dispatch_session_replay_revocation_and_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            with serve_gateway_session(
                    path, key=self.key, audience="gway-001",
                    verifier=self.verifier, session_token="gateway-token",
                    allowed_node=lambda token, node: node == "gway-001",
                    read_principal=lambda token: "reader",
                    execution=self.execution, inventory=Inventory()) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    read = self.envelope()
                    self.assertEqual(call_unix(path, self.key, read)["nodes"], [])
                    with self.assertRaises(PermissionError):
                        call_unix(path, self.key, read)
                    execute = self.envelope(
                        operation="execution.start", scope="gway:execute",
                        principal="a" * 24, nonce="c",
                        arguments={"node": "gway-001", "command": "true",
                                   "request_id": "d" * 32})
                    self.assertEqual(call_unix(path, self.key, execute),
                                     {"status": "dispatched"})
                    self.assertEqual(self.execution.calls[0]["principal"], "a" * 24)
                    self.verifier.active = False
                    with self.assertRaises(PermissionError):
                        call_unix(path, self.key, self.envelope(nonce="e"))
                finally:
                    server.shutdown()
                    thread.join(timeout=3)

    def test_node_not_authorized_cannot_bind(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PermissionError):
                serve_gateway_session(
                    Path(directory) / "bridge.sock",
                    key=self.key, audience="gway-001",
                    verifier=self.verifier, session_token="gateway-token",
                    allowed_node=lambda token, node: False,
                    read_principal=lambda token: "reader")


if __name__ == "__main__":
    unittest.main()
