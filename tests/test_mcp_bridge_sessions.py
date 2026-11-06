import tempfile
import threading
import time
import unittest
from pathlib import Path

from gway_remote.mcp_bridge_sessions import BridgeSessions
from gway_remote.mcp_bridge_transport import AuthenticatedBridge, BridgeUnixServer, call_unix


class Verifier:
    valid = True
    def verify(self, token, *, required_scope):
        return self.valid and token == "trusted" and required_scope == "gway:read"


class Inventory:
    def public_nodes(self, *, execution_enabled):
        return {"nodes": [], "execution_enabled": execution_enabled}


class SessionManagerTests(unittest.TestCase):
    def test_signed_session_socket_and_revocation(self):
        verifier = Verifier()
        sessions = BridgeSessions(
            verifier=verifier, allowed_node=lambda token, node: node == "gway-001",
            read_principal=lambda token: "reader", inventory=Inventory())
        sid = sessions.register(token="trusted", audience="gway-001")
        now = int(time.time())
        envelope = {"version": 1, "request_id": "a" * 32,
                    "principal": "reader", "audience": "gway-001",
                    "operation": "inventory.list", "scope": "gway:read",
                    "issued_at": now, "expires_at": now + 30, "arguments": {}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            bridge = AuthenticatedBridge(b"k" * 32, audience="gway-001",
                                         dispatch=None, sessions=sessions)
            with BridgeUnixServer(path, bridge) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    self.assertEqual(call_unix(path, b"k" * 32, envelope,
                                               session_id=sid)["nodes"], [])
                    envelope["request_id"] = "b" * 32
                    with self.assertRaises(PermissionError):
                        call_unix(path, b"k" * 32, envelope, session_id="f" * 48)
                    sessions.revoke(sid)
                    envelope["request_id"] = "c" * 32
                    with self.assertRaises(PermissionError):
                        call_unix(path, b"k" * 32, envelope, session_id=sid)
                finally:
                    server.shutdown()
                    thread.join(timeout=3)

    def test_capacity(self):
        sessions = BridgeSessions(
            verifier=Verifier(), allowed_node=lambda token, node: True,
            read_principal=lambda token: "reader", max_sessions=1)
        sessions.register(token="trusted", audience="gway-001")
        with self.assertRaises(PermissionError):
            sessions.register(token="trusted", audience="gway-001")


if __name__ == "__main__":
    unittest.main()
