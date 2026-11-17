"""P2: control-plane isolation and authenticated per-node bridge dispatch.

All tests run with local HTTP/Unix sockets and fakes; no node/SSH effects.
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import make_server
from gway_remote.mcp_bridge_gateway_dispatch import (
    CONTROL_AUDIENCE, resolve_bridge_audience,
)
from gway_remote.mcp_bridge_sessions import BridgeSessions
from gway_remote.mcp_bridge_transport import (
    AuthenticatedBridge, BridgeUnixServer, call_unix,
)
from gway_remote.mcp_bridge_bootstrap import bridge_node_allowed
from tests.helpers.mcp_http import mcp_call, bearer_post


class Ledger:
    def __init__(self):
        self.rows = {}

    def get(self, request_id):
        if request_id not in self.rows:
            raise ValueError("request not found")
        return dict(self.rows[request_id])


class FakeExecution:
    def __init__(self):
        self.ledger = Ledger()
        self.active = {"gway-002", "gway-004"}
        self.calls = []

    def _current_eligibility(self, node):
        if node not in self.active:
            raise PermissionError("node not enrolled/eligible")

    def _owned(self, principal, request_id):
        row = self.ledger.get(request_id)
        if row["principal"] != principal:
            raise PermissionError("unowned request")
        self._current_eligibility(row["node"])
        return row

    def exec(self, *, principal, node, command, request_id, **kwargs):
        self._current_eligibility(node)
        self.calls.append(("submit", node, request_id))
        self.ledger.rows.setdefault(
            request_id, {"node": node, "principal": principal})
        return {"node": node, "request_id": request_id, "status": "dispatched"}

    def result(self, *, principal, request_id, cursor=0):
        row = self._owned(principal, request_id)
        self.calls.append(("result", row["node"], request_id))
        return {"node": row["node"], "request_id": request_id, "status": "running"}

    def cancel(self, *, principal, request_id):
        row = self._owned(principal, request_id)
        self.calls.append(("cancel", row["node"], request_id))
        return {"node": row["node"], "request_id": request_id, "status": "cancelled"}


class Inventory:
    def public_nodes(self, *, execution_enabled):
        return {"nodes": [{"node": "gway-002"}, {"node": "gway-004"}]}
    def capabilities(self, node, *, execution_enabled):
        return {"node": node, "execute_available": node in ("gway-002", "gway-004")}


class AudienceResolutionTests(unittest.TestCase):
    def setUp(self):
        self.exec = FakeExecution()
        self.owner = "a" * 24
        self.request_id = "c" * 32
        self.exec.ledger.rows[self.request_id] = {"principal": self.owner, "node": "gway-002"}

    def resolve(self, name, args, *, owner=None):
        return resolve_bridge_audience(name, args, execution=self.exec,
                                       principal=self.owner if owner is None else owner)

    def test_inventory_is_watchtower_control_plane(self):
        self.assertEqual(self.resolve("node_list", {}), CONTROL_AUDIENCE)
        self.assertEqual(self.resolve("node_capabilities", {"node": "gway-005"}),
                         CONTROL_AUDIENCE)
        self.assertFalse(bridge_node_allowed(None, "gway-002"))
        self.assertTrue(bridge_node_allowed(None, CONTROL_AUDIENCE))

    def test_targeted_tools_are_not_routed_to_001(self):
        for name in ("node_exec", "node_file_download", "workspace_inspect",
                     "node_deploy", "node_deploy_preview", "node_exec_preview"):
            with self.subTest(name=name):
                self.assertEqual(self.resolve(name, {"node": "gway-004"}), "gway-004")
        for node in ("gway-000", "arbitrary.example", "", 5):
            with self.subTest(node=node), self.assertRaises(PermissionError):
                self.resolve("node_exec", {"node": node})

    def test_result_cancel_and_deploy_status_derive_original_owned_node(self):
        for name, args in (
            ("node_result", {"request_id": self.request_id}),
            ("node_cancel", {"request_id": self.request_id}),
            ("node_deploy_status", {"node": "gway-002", "request_id": self.request_id}),
        ):
            self.assertEqual(self.resolve(name, args), "gway-002")
        for name in ("node_result", "node_cancel", "node_deploy_status"):
            with self.subTest(name=name), self.assertRaises(PermissionError):
                self.resolve(name, {"node": "gway-004",
                                    "request_id": self.request_id})
        with self.assertRaises(PermissionError):
            self.resolve("node_result", {"request_id": self.request_id}, owner="b" * 24)
        with self.assertRaises(ValueError):
            self.resolve("node_cancel", {"request_id": "bad"})
        self.exec.active.remove("gway-002")
        with self.assertRaises(PermissionError):
            self.resolve("node_result", {"request_id": self.request_id})

    def test_bootstrap_rechecks_current_node_eligibility(self):
        self.assertTrue(bridge_node_allowed(self.exec, "gway-004"))
        self.assertFalse(bridge_node_allowed(self.exec, "gway-005"))
        self.exec.active.remove("gway-004")
        self.assertFalse(bridge_node_allowed(self.exec, "gway-004"))


class ManagedBridgeHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.execution = FakeExecution()
        self.registry = BearerRegistry(Path(self.temp.name) / "auth.sqlite")
        self.read_token = self.registry.issue()
        parent = self.registry.issue(scope="gway:execute", operator_approved=True)
        self.owner = parent.split("_", 2)[1]
        self.execute_token = self.registry.issue(
            scope="gway:execute", parent_id=self.owner)
        self.verifier = BearerVerifier(self.registry.path)
        self.key = b"k" * 32
        self.sessions = BridgeSessions(
            verifier=self.verifier,
            allowed_node=lambda token, node: bridge_node_allowed(self.execution, node),
            read_principal=lambda token: token.split("_", 2)[1],
            execution=self.execution, inventory=Inventory())
        self.socket_path = Path(self.temp.name) / "bridge.sock"
        self.bridge = BridgeUnixServer(
            self.socket_path,
            AuthenticatedBridge(self.key, audience=None, dispatch=None,
                                sessions=self.sessions))
        self.addCleanup(self.bridge.server_close)
        self.bridge_thread = threading.Thread(
            target=self.bridge.serve_forever, daemon=True)
        self.bridge_thread.start()
        self.addCleanup(self.bridge_thread.join)
        self.addCleanup(self.bridge.shutdown)
        self.gateway = make_server(
            ("127.0.0.1", 0), self.verifier, "http://127.0.0.1:1/mcp",
            "private-backend-only", execution=self.execution,
            bridge_sessions=self.sessions,
            bridge_transport=(str(self.socket_path), self.key))
        self.addCleanup(self.gateway.server_close)
        self.gateway_thread = threading.Thread(
            target=self.gateway.serve_forever, daemon=True)
        self.gateway_thread.start()
        self.addCleanup(self.gateway_thread.join)
        self.addCleanup(self.gateway.shutdown)

    def call(self, name, arguments, *, token=None):
        endpoint = "http://127.0.0.1:%s/mcp" % self.gateway.server_port
        request = bearer_post(endpoint, mcp_call(name, arguments),
                              token if token is not None else self.execute_token)
        try:
            with urlopen(request, timeout=6) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            status = exc.code
            exc.close()
            return status, None

    def decoded(self, name, args, *, token=None):
        status, response = self.call(name, args, token=token)
        self.assertEqual(status, 200)
        result = response["result"]
        self.assertFalse(result.get("isError"), result)
        return json.loads(result["content"][0]["text"])

    def test_002_and_004_work_without_001_or_the_private_backend(self):
        inventory = self.decoded("node_list", {}, token=self.read_token)
        self.assertEqual([n["node"] for n in inventory["nodes"]],
                         ["gway-002", "gway-004"])
        self.assertEqual(self.decoded(
            "node_capabilities", {"node": "gway-005"},
            token=self.read_token)["node"], "gway-005")
        for node, job in (("gway-002", "a" * 32), ("gway-004", "b" * 32)):
            self.assertEqual(self.decoded(
                "node_exec", {"node": node, "command": "true",
                              "request_id": job})["node"], node)
        self.assertEqual(self.execution.calls[:2], [
            ("submit", "gway-002", "a" * 32),
            ("submit", "gway-004", "b" * 32),
        ])
        self.assertEqual(self.decoded(
            "node_result", {"request_id": "a" * 32})["node"], "gway-002")
        self.assertEqual(self.decoded(
            "node_cancel", {"request_id": "b" * 32})["node"], "gway-004")
        self.assertEqual(len(self.sessions.sessions), 0)

    def test_cross_node_spoofing_denial_and_scope(self):
        status, rejected = self.call(
            "node_exec", {"node": "gway-002", "command": "true",
                          "request_id": "a" * 32}, token=self.read_token)
        self.assertEqual(status, 200)
        self.assertTrue(rejected["result"]["isError"])
        self.assertFalse(self.execution.calls)
        self.assertEqual(self.call("node_exec", {"node": "gway-005",
              "command": "true", "request_id": "d" * 32})[1]["result"]["isError"], True)
        self.assertEqual(self.call("node_result",
                          {"request_id": "f" * 32})[1]["result"]["isError"], True)
        self.assertFalse(self.execution.calls)

    def test_revocation_drops_subsequent_result_without_redispatch(self):
        job = "e" * 32
        self.decoded("node_exec", {"node": "gway-002", "command": "true",
                                    "request_id": job})
        self.execution.active.remove("gway-002")
        self.assertTrue(self.call("node_result", {"request_id": job})[1]["result"]["isError"])
        self.assertEqual(self.execution.calls, [("submit", "gway-002", job)])

    def test_signed_envelope_cannot_reuse_one_session_for_another_node(self):
        sid = self.sessions.register(token=self.read_token, audience="gway-002")
        try:
            now = int(time.time())
            raw = {"version": 1, "request_id": "f" * 32,
                   "principal": self.read_token.split("_", 2)[1],
                   "audience": "gway-004", "operation": "inventory.list",
                   "scope": "gway:read", "issued_at": now,
                   "expires_at": now + 30, "arguments": {}}
            with self.assertRaises(PermissionError):
                call_unix(self.socket_path, self.key, raw,
                          session_id=sid, require_signed_reply=True)
        finally:
            self.sessions.revoke(sid)


if __name__ == "__main__":
    unittest.main()
