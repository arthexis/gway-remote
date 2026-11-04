"""Execution authorization: no manual approval, no dispatch to ineligible nodes."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.watchtower_exec_transport import RequestLedger
from gway_remote.watchtower_exec_auth import AuthorizedExecution
from gway_remote.mcp_bearer_gateway import EXEC_TOOL_NAMES, EXEC_TOOLS, inspect_rpc, payload_is_exec, make_server


class ExecuteScopeTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.registry = BearerRegistry(Path(self.t.name) / "bearers.sqlite3")

    def test_execute_requires_console_proof_not_per_command_approval(self):
        read = self.registry.issue()
        verifier = BearerVerifier(self.registry.path)
        self.assertTrue(verifier.verify(read))
        self.assertFalse(verifier.verify(read, required_scope="gway:execute"))
        with self.assertRaises(PermissionError):
            self.registry.issue(scope="gway:execute")
        with self.assertRaises(ValueError):
            self.registry.issue(scope="gway:execute", parent_id=read.split("_")[1])
        execute = self.registry.issue(scope="gway:execute", operator_approved=True)
        delegated = self.registry.issue(scope="gway:execute", parent_id=execute.split("_")[1])
        self.assertTrue(verifier.verify(delegated, required_scope="gway:execute"))
        self.assertEqual(verifier.execution_principal(delegated), execute.split("_")[1])
        self.assertEqual(verifier.execution_principal(execute), execute.split("_")[1])
        self.registry.revoke(execute.split("_")[1])
        self.assertFalse(verifier.verify(delegated, required_scope="gway:execute"))
        with self.assertRaises(PermissionError):
            verifier.execution_principal(delegated)

    def test_exec_contract_has_no_manual_approval(self):
        spec = next(tool for tool in EXEC_TOOLS if tool["name"] == "node_exec")
        self.assertEqual(spec["inputSchema"]["required"], ["node", "command", "request_id"])
        self.assertNotIn("approval", spec["inputSchema"]["properties"])
        for name in EXEC_TOOL_NAMES:
            raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": name, "arguments": {}}}).encode()
            self.assertTrue(inspect_rpc(raw))
            self.assertTrue(payload_is_exec(raw))
        with make_server(("127.0.0.1", 0), None, "http://127.0.0.1:19011/mcp", "fixed") as server:
            self.assertIsNone(server.execution)


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        root = Path(self.t.name) / "private"
        root.mkdir(mode=0o700)
        self.ledger = RequestLedger(root / "requests.sqlite3")
        self.id = "a" * 32
        self.principal = "b" * 24

        class Node:
            node = "gway-001"
            wireguard_address = "10.90.0.2"
            host_key_sha256 = "c" * 64
        class Transport:
            node = Node()
        class Relay:
            transport = Transport()
            enabled = True
            calls = 0
            def dispatch(self, request_id):
                self.calls += 1
                return "dispatched"
            def result(self, request_id, cursor=0):
                return {"request_id": request_id, "cursor": cursor}
            def cancel(self, request_id):
                return {"request_id": request_id, "status": "cancel_requested"}
        self.relay = Relay()
        self.service = AuthorizedExecution(self.ledger, None, self.relay, enabled=True)
        self.granted = {"nodes": [{"node": "gway-001", "registered": True,
                         "identity_verified": True, "execute_eligible": True,
                         "reachable": "reachable", "address": "10.90.0.2"}]}

    def submit(self, **changes):
        params = {"principal": self.principal, "request_id": self.id,
                  "node": "gway-001", "command": "uptime"}
        params.update(changes)
        return self.service.exec(**params)

    def test_two_distinct_commands_without_manual_approval(self):
        with patch("gway_remote.node_registry_inventory.load", return_value=self.granted):
            self.assertEqual(self.submit()["status"], "dispatched")
            self.assertEqual(self.submit(request_id="d"*32, command="hostname")["status"], "dispatched")
        self.assertEqual(self.relay.calls, 2)

    def test_duplicate_id_and_mutation_deny_redispatch(self):
        with patch("gway_remote.node_registry_inventory.load", return_value=self.granted):
            self.submit()
            self.assertEqual(self.submit()["status"], "reserved")
            with self.assertRaises(PermissionError):
                self.submit(command="id")
            with self.assertRaises(PermissionError):
                self.submit(principal="f"*24)
        self.assertEqual(self.relay.calls, 1)

    def test_revoked_eligibility_rejected_before_dispatch(self):
        denied = {"nodes": [{**self.granted["nodes"][0], "execute_eligible": False}]}
        with patch("gway_remote.node_registry_inventory.load", return_value=denied):
            with self.assertRaises(PermissionError):
                self.submit()
        self.assertEqual(self.relay.calls, 0)

    def test_result_cancel_bound_to_requester(self):
        with patch("gway_remote.node_registry_inventory.load", return_value=self.granted):
            self.submit()
        with self.assertRaises(PermissionError):
            self.service.result(principal="f"*24, request_id=self.id)
        with self.assertRaises(PermissionError):
            self.service.cancel(principal="f"*24, request_id=self.id)


if __name__ == "__main__":
    unittest.main()
