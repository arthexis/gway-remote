"""B2b-3 authorization tests: no real sshd, systemd or remote command execution."""
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.watchtower_exec_transport import RequestLedger
from gway_remote.watchtower_exec_auth import ExecutionApprovals, AuthorizedExecution
from gway_remote.mcp_bearer_gateway import (
    EXEC_TOOL_NAMES, EXEC_TOOLS, inspect_rpc, payload_is_exec, make_server,
)
import json


class ExecuteScopeTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.registry = BearerRegistry(Path(self.t.name) / "bearers.sqlite3")

    def test_read_token_cannot_execute_and_execute_token_requires_operator(self):
        read = self.registry.issue()
        verifier = BearerVerifier(self.registry.path)
        self.assertTrue(verifier.verify(read))
        self.assertFalse(verifier.verify(read, required_scope="gway:execute"))
        with self.assertRaises(PermissionError):
            self.registry.issue(scope="gway:execute")
        with self.assertRaises(PermissionError):
            self.registry.issue(scope="gway:execute",parent_id=read.split("_")[1])
        execute = self.registry.issue(scope="gway:execute",operator_approved=True)
        self.assertTrue(verifier.verify(execute,required_scope="gway:execute"))
        self.assertFalse(verifier.verify(execute,required_scope="gway:read"))
        self.registry.revoke(execute.split("_")[1])
        self.assertFalse(verifier.verify(execute,required_scope="gway:execute"))

    def test_exec_tool_rpc_is_recognized_but_not_advertised_by_default(self):
        for name in EXEC_TOOL_NAMES:
            raw=json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/call",
                            "params":{"name":name,"arguments":{}}}).encode()
            self.assertTrue(inspect_rpc(raw))
            self.assertTrue(payload_is_exec(raw))
        with make_server(("127.0.0.1",0),None,"http://127.0.0.1:19011/mcp","fixed") as server:
            self.assertIsNone(server.execution)


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)
        self.root.chmod(0o700)
        self.ledger=RequestLedger(self.root/"requests.sqlite3")
        self.approvals=ExecutionApprovals(self.ledger)
        self.id="a"*32
        self.principal="b"*24
        self.host="c"*64

    def issue(self, **kwargs):
        args={"principal":self.principal,"node":"gway-001","command":"uptime",
              "request_id":self.id,"host_sha256":self.host,"issued_by":"operator"}
        args.update(kwargs)
        return self.approvals.issue(**args)

    def consume(self, approval, **kwargs):
        args={"approval":approval,"principal":self.principal,"node":"gway-001",
              "command":"uptime","request_id":self.id,"host_sha256":self.host}
        args.update(kwargs)
        return self.approvals.consume(**args)

    def test_one_use_exact_binding(self):
        token=self.issue()["approval"]
        self.assertIsNotNone(self.consume(token))
        with self.assertRaises(PermissionError):
            self.consume(token)

    def test_reject_all_modified_fields_before_consuming(self):
        args=({"principal":"d"*24},{"node":"gway-002"},{"command":"id"},
              {"request_id":"e"*32},{"host_sha256":"f"*64})
        for change in args:
            with self.subTest(change=change):
                token=self.issue()["approval"]
                with self.assertRaises(PermissionError):
                    self.consume(token,**change)
                self.assertIsNotNone(self.consume(token))

    def test_expired_approval_cannot_be_consumed(self):
        issued=self.issue(ttl_seconds=10)
        with self.ledger.connection() as db:
            db.execute("UPDATE exec_approvals SET expires_at=? WHERE request_id=?",
                       ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),self.id))
        with self.assertRaises(PermissionError):
            self.consume(issued["approval"])

    def test_authorization_guard_before_transport(self):
        class Node:
            node="gway-001"
            host_key_sha256="c"*64
        class Transport:
            node=Node()
            def invoke(self, payload):
                raise AssertionError("unexpected remote invocation")
        class FakeRelay:
            transport=Transport()
            enabled=False
        controller=AuthorizedExecution(self.ledger,self.approvals,FakeRelay(),enabled=False)
        token=self.issue()["approval"]
        with self.assertRaises(PermissionError):
            controller.exec(principal=self.principal,request_id=self.id,node="gway-001",
                            command="uptime",approval=token)
        with self.assertRaises(PermissionError):
            controller.result(principal=self.principal,request_id=self.id)
        with self.assertRaises(PermissionError):
            controller.cancel(principal=self.principal,request_id=self.id)
        self.assertEqual(self.ledger.connection is not None,True)
        self.assertIsNotNone(self.consume(token))


if __name__=="__main__":
    unittest.main()
