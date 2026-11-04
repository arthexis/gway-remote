"""B2b-2 dormant bridge contract: no live SSH, node shell or MCP dispatch."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gway_remote.watchtower_exec_transport import (
    DormantRelay, PinnedNode, RequestLedger, SSHTransport,
)
from gway_remote.node_exec_protocol import serve_one


class WatchtowerLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.db = self.root / "requests.sqlite3"
        self.ledger = RequestLedger(self.db)
        self.id = "a" * 32
        self.hostkey = "b" * 64
        self.exp = (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat()

    def reserve(self, **changes):
        args = {"request_id":self.id,"node":"gway-001","command":"uptime",
                "principal":"alice","host_key_sha256":self.hostkey,
                "expires_at":self.exp}
        args.update(changes)
        return self.ledger.reserve(**args)

    def test_persists_across_instances_and_reserves_once(self):
        self.assertEqual(self.reserve()["state"], "reserved")
        self.assertEqual(RequestLedger(self.db).reserve(
            request_id=self.id,node="gway-001",command="uptime",
            principal="alice",host_key_sha256=self.hostkey,
            expires_at=self.exp)["request_id"], self.id)
        self.assertTrue(self.ledger.claim_dispatch(self.id))
        self.assertFalse(RequestLedger(self.db).claim_dispatch(self.id))
        self.ledger.mark_dispatched(self.id, confirmed=False)
        self.assertEqual(RequestLedger(self.db).get(self.id)["state"],"uncertain")
        self.assertFalse(self.ledger.claim_dispatch(self.id))

    def test_reused_id_conflicts_on_any_binding_change(self):
        self.reserve()
        for change in ({"command":"whoami"}, {"node":"gway-002"},
                       {"principal":"bob"}, {"host_key_sha256":"c"*64},
                       {"expires_at":(datetime.now(timezone.utc)+timedelta(minutes=4)).isoformat()}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError,"reused"):
                self.reserve(**change)

    def test_expiry_and_unknown_id_fail_closed(self):
        past=(datetime.now(timezone.utc)-timedelta(seconds=2)).isoformat()
        with self.assertRaisesRegex(ValueError,"expired"):
            self.reserve(expires_at=past)
        with self.assertRaisesRegex(ValueError,"not found"):
            self.ledger.claim_dispatch("b"*32)
        self.reserve()
        with self.ledger.connection() as db:
            db.execute("UPDATE requests SET expires_at=? WHERE request_id=?",(past,self.id))
        with self.assertRaisesRegex(ValueError,"expired"):
            self.ledger.claim_dispatch(self.id)

    def test_ledger_storage_private(self):
        self.reserve()
        self.assertEqual(self.db.stat().st_mode & 0o777,0o600)
        self.root.chmod(0o755)
        with self.assertRaises(PermissionError):
            self.ledger.get(self.id)

    def test_dormant_relay_never_invokes_transport(self):
        self.reserve()
        class FakeTransport:
            class FakeNode:
                node="gway-001"
                host_key_sha256="b"*64
            node=FakeNode()
            def invoke(self, payload):
                raise AssertionError("should not dispatch")
        with self.assertRaisesRegex(PermissionError,"disabled"):
            DormantRelay(self.ledger,FakeTransport()).dispatch(self.id)
        self.assertEqual(self.ledger.get(self.id)["state"],"reserved")

    def test_dispatch_crash_unknown_no_replay(self):
        self.reserve()
        class FakeTransport:
            class FakeNode:
                node="gway-001"
                host_key_sha256="b"*64
            node=FakeNode()
            calls=0
            def invoke(self, payload):
                self.calls+=1
                raise OSError("lost SSH")
        transport=FakeTransport()
        relay=DormantRelay(self.ledger,transport,enabled=True)
        self.assertEqual(relay.dispatch(self.id),"uncertain")
        self.assertEqual(relay.dispatch(self.id),"uncertain")
        self.assertEqual(transport.calls,1)


class SSHBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.private=self.root/"key"
        self.private.write_bytes(b"fixture")
        self.private.chmod(0o600)
        key=b"fixed-public-host-key-fixture"
        self.fp=hashlib.sha256(key).hexdigest()
        self.known=self.root/"known_hosts"
        self.known.write_text("gway-001 ssh-ed25519 "+base64.b64encode(key).decode()+"\n")
        self.known.chmod(0o600)

    def node(self, **changes):
        fields={"node":"gway-001","wireguard_address":"10.6.0.2",
                "ssh_host_alias":"gway-001","known_hosts":self.known,
                "identity_file":self.private,"host_key_sha256":self.fp,
                "remote_user":"gway-relay"}
        fields.update(changes)
        return PinnedNode(**fields)

    def test_fixed_ssh_argv_no_client_shell_or_hostname(self):
        seen=[]
        def fake(argv, **kwargs):
            seen.append((argv,kwargs))
            raw=json.loads(kwargs["input"])
            return subprocess.CompletedProcess(argv,0,
                json.dumps({"node":"gway-001","request_id":raw["request_id"],
                            "status":"accepted"}).encode(),b"")
        result=SSHTransport(self.node(),run=fake).invoke(
            {"operation":"submit","node":"gway-001","request_id":"c"*32,
             "command":"echo hello; touch /tmp/test"})
        self.assertEqual(result["status"],"accepted")
        argv,kwargs=seen[0]
        self.assertIn("StrictHostKeyChecking=yes",argv)
        self.assertIn("HostKeyAlias=gway-001",argv)
        self.assertEqual(argv[-2:],["10.6.0.2","gway-exec-protocol-v1"])
        self.assertNotIn("echo hello"," ".join(argv))
        self.assertIn("-F",argv)
        self.assertEqual(kwargs["timeout"],15)

    def test_fails_on_host_key_change_and_bad_node(self):
        for kwargs in ({"host_key_sha256":"0"*64},
                       {"node":"gway-002"},
                       {"wireguard_address":"127.0.0.1"},
                       {"wireguard_address":"host;sh"}):
            with self.subTest(kwargs=kwargs),self.assertRaises((ValueError,PermissionError)):
                self.node(**kwargs)
        self.private.chmod(0o666)
        with self.assertRaises(PermissionError):
            self.node()

    def test_rejects_foreign_response_and_unexpected_fields(self):
        def fake(argv,**kwargs):
            return subprocess.CompletedProcess(argv,0,
                json.dumps({"node":"gway-002","request_id":"a"*32}).encode(),b"")
        bridge=SSHTransport(self.node(),run=fake)
        with self.assertRaisesRegex(ValueError,"incorrect node"):
            bridge.invoke({"operation":"cancel","node":"gway-001","request_id":"a"*32})
        with self.assertRaisesRegex(ValueError,"unexpected"):
            bridge.invoke({"operation":"cancel","node":"gway-001",
                           "request_id":"a"*32,"host":"evil"})


class NodeProtocolTests(unittest.TestCase):
    def test_fixed_message_shapes_and_node_binding(self):
        class FakeJobs:
            def __init__(self):
                self.calls=[]
            def submit(self,node,command,request_id):
                self.calls.append((node,command,request_id))
            def row(self,rid):
                return {"node":"gway-001"}
            def cancel(self,rid):
                return "cancel_requested"
            def result(self,rid,cursor):
                return {"node":"gway-001","request_id":rid,"status":"running"}
        jobs=FakeJobs()
        with patch("gway_remote.node_exec_protocol.require_account"):
            raw=json.dumps({"operation":"submit","node":"gway-001",
                "request_id":"c"*32,"command":"uptime"}).encode()
            self.assertEqual(serve_one(raw,jobs=jobs,hostname="gway-001")["status"],"accepted")
            self.assertEqual(len(jobs.calls),1)
            with self.assertRaises(ValueError):
                serve_one(raw[:-1],jobs=jobs,hostname="gway-001")
            with self.assertRaises(PermissionError):
                serve_one(raw,jobs=jobs,hostname="gway-002")
            malicious=json.dumps({"operation":"submit","node":"gway-001",
                "request_id":"c"*32,"command":"uptime","approved":True}).encode()
            with self.assertRaisesRegex(ValueError,"fields"):
                serve_one(malicious,jobs=jobs,hostname="gway-001")
        self.assertEqual(len(jobs.calls),1)


if __name__=="__main__":
    unittest.main()
