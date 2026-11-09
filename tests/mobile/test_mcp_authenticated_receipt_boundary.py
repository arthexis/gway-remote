"""HTTP -> signed Unix bridge -> session authorization -> receipt negatives.

No real SSH, node command, or deployment is invoked.
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from unittest.mock import Mock

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import make_server
from gway_remote.mcp_bridge_sessions import BridgeSessions
from gway_remote.mcp_bridge_transport import AuthenticatedBridge, BridgeUnixServer, call_unix
from gway_remote.mcp_bridge_gateway_dispatch import dispatch_node_tool


class AuthenticatedReceiptBoundaryTests(unittest.TestCase):
    def test_wrong_principal_session_node_never_poison_receipt_or_dispatch(self):
        with tempfile.TemporaryDirectory() as home:
            registry = BearerRegistry(Path(home) / "tokens.db")
            owner = registry.issue(scope="gway:execute", operator_approved=True)
            other = registry.issue(scope="gway:execute", operator_approved=True)
            verifier = BearerVerifier(registry.path)
            principal = verifier.execution_principal(owner)
            executor = Mock()
            rid = "e" * 32
            executor.exec.return_value = {
                "node": "gway-001", "request_id": rid, "status": "uncertain",
                "failure_stage": "worker_readiness"}
            sessions = BridgeSessions(
                verifier=verifier, allowed_node=lambda token, node: node == "gway-001",
                read_principal=lambda token: "reader", execution=executor)
            key = b"k" * 32
            path = Path(home) / "bridge.sock"
            bridge = AuthenticatedBridge(
                key, audience="gway-001", dispatch=lambda _: None, sessions=sessions)
            with BridgeUnixServer(path, bridge) as socket_server:
                with make_server(("127.0.0.1", 0), verifier,
                                 "http://127.0.0.1:19011/mcp", "backend-secret",
                                 execution=executor, bridge_sessions=sessions,
                                 bridge_transport=(str(path), key, "gway-001")) as gateway:
                    socket_thread = threading.Thread(
                        target=socket_server.serve_forever, daemon=True)
                    http_thread = threading.Thread(
                        target=gateway.serve_forever, daemon=True)
                    socket_thread.start()
                    http_thread.start()
                    try:
                        endpoint = "http://127.0.0.1:%d/mcp" % gateway.server_port

                        def call(token, name, arguments):
                            body = json.dumps({"jsonrpc": "2.0", "id": 1,
                                "method": "tools/call", "params": {
                                    "name": name, "arguments": arguments}}).encode()
                            request = Request(endpoint, body, {
                                "Authorization": "Bearer " + token,
                                "Content-Type": "application/json"}, method="POST")
                            with urlopen(request, timeout=4) as response:
                                return json.loads(response.read())["result"]

                        args = {"node": "gway-001", "command": "true",
                                "request_id": rid}
                        # The wrong node is rejected before dispatch or receipt.
                        rejected = call(owner, "node_exec", {**args, "node": "gway-002"})
                        self.assertTrue(rejected.get("isError"))
                        self.assertEqual(executor.exec.call_count, 0)

                        # A genuine signed request cannot claim another OAuth principal.
                        sid = sessions.register(token=owner, audience="gway-001")
                        now = int(time.time())
                        forged = {"version": 1, "request_id": "f" * 32,
                                  "principal": verifier.execution_principal(other),
                                  "audience": "gway-001", "operation": "execution.start",
                                  "scope": "gway:execute", "issued_at": now,
                                  "expires_at": now + 30, "arguments": args}
                        with self.assertRaises(PermissionError):
                            call_unix(path, key, forged, session_id=sid,
                                      require_signed_reply=True)
                        with self.assertRaises(PermissionError):
                            call_unix(path, key, {**forged,
                                "request_id": "a" * 32, "principal": principal},
                                session_id="0" * 48, require_signed_reply=True)
                        self.assertEqual(executor.exec.call_count, 0)

                        unknown = call(owner, "node_exec_diagnostic",
                                       {"request_id": rid})
                        self.assertEqual(json.loads(unknown["content"][0]["text"])["status"],
                                         "unknown")
                        # A correlated signed result creates exactly one receipt.
                        accepted = call(owner, "node_exec", args)
                        self.assertEqual(json.loads(accepted["content"][0]["text"])["status"],
                                         "uncertain")
                        self.assertEqual(executor.exec.call_count, 1)
                        own = call(owner, "node_exec_diagnostic", {"request_id": rid})
                        self.assertEqual(json.loads(own["content"][0]["text"])["stage"],
                                         "worker_readiness")
                        outsider = call(other, "node_exec_diagnostic", {"request_id": rid})
                        self.assertEqual(json.loads(outsider["content"][0]["text"])["status"],
                                         "unknown")
                        self.assertEqual(executor.exec.call_count, 1)
                    finally:
                        gateway.shutdown()
                        socket_server.shutdown()
                        http_thread.join(timeout=3)
                        socket_thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
