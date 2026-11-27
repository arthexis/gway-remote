"""Native cross-node coordination: no GitHub, no HTTP, no shell authority."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock, patch

from gway_remote import agentops_coordination as c
from gway_remote.node_exec_protocol import serve_one

EPOCH="a"*32
NODES=["gway-001","gway-004"]
REPO="b"*64
IDENT="c"*64
HIST="d"*64

def intent(identity=IDENT,token="e"*32,repo=REPO,state="pending"):
    return {"repo":repo,"identity":identity,"token":token,"state":state}


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"state.sqlite3"
        self.ledger=c.Ledger(self.path,epoch=EPOCH,members=NODES)
        self.ledger.initialize([HIST])

    def test_simultaneous_two_node_reservation_and_replay(self):
        gate=Barrier(2)
        def attempt(node):
            gate.wait(timeout=5)
            return self.ledger.resolve(node,intent(token=("1" if node==NODES[0] else "2")*32))
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows=list(pool.map(attempt,NODES))
        self.assertEqual(sorted(row["state"] for row in rows),["replayed","reserved"])
        winner=next(i for i,r in enumerate(rows) if r["state"]=="reserved")
        loser=1-winner
        claim=rows[winner]
        self.assertEqual(self.ledger.resolve(NODES[winner],{**claim,"state":"pending"}),claim)
        different=intent("f"*64,token="3"*32)
        self.assertEqual(self.ledger.resolve(NODES[loser],different)["state"],"busy")
        with self.assertRaises(ValueError):
            self.ledger.resolve(NODES[loser],{**claim,"state":"terminal"})
        with self.assertRaises(ValueError):
            self.ledger.resolve(NODES[winner],{**claim,"state":"terminal","token":"0"*32})
        self.assertEqual(self.ledger.resolve(NODES[winner],{**claim,"state":"terminal"})["state"],"released")
        self.assertEqual(self.ledger.resolve(NODES[winner],{**claim,"state":"terminal"})["state"],"released")
        self.assertEqual(self.ledger.resolve(NODES[loser],different)["state"],"reserved")
        self.assertEqual(self.ledger.resolve(NODES[winner],{**claim,"state":"pending"})["state"],"replayed")
        self.assertEqual(self.ledger.resolve(NODES[0],intent(HIST))["state"],"replayed")
        self.assertEqual(self.ledger.counts(),{"historical":1,"released":1,"reserved":1})

    def test_missing_or_wrong_epoch_never_creates_or_resets(self):
        with self.assertRaises((OSError,ValueError)):
            c.Ledger(self.path.with_name("absent"),epoch=EPOCH,members=NODES).resolve(NODES[0],intent())
        self.assertFalse(self.path.with_name("absent").exists())
        with self.assertRaises(ValueError):
            c.Ledger(self.path,epoch="9"*32,members=NODES).resolve(NODES[0],intent())
        with self.assertRaises(FileExistsError):
            self.ledger.initialize([])

    def test_lost_ack_does_not_release_or_redispatch(self):
        first=intent()
        class Wire:
            fail=True
            def invoke(self,p):
                node=p["node"]; op=p["operation"]
                if op.endswith("snapshot"):
                    data={"node":node,"epoch":EPOCH,"intents":[first] if node==NODES[0] else []}
                else:
                    if self.fail: raise OSError("lost ack")
                    data={"node":node,"epoch":EPOCH,"applied":len(p["decisions"])}
                return {"node":node,"request_id":p["request_id"],"result":data}
        wire=Wire()
        self.assertEqual(c.tick(self.ledger,wire)[NODES[0]]["state"],"unavailable")
        self.assertEqual(self.ledger.counts()["reserved"],1)
        wire.fail=False
        self.assertEqual(c.tick(self.ledger,wire)[NODES[0]]["state"],"ok")
        self.assertEqual(self.ledger.counts()["reserved"],1)

    def test_node_verb_not_public_and_requires_relay(self):
        req={"operation":"agentops_coordination_snapshot","node":NODES[0],
             "request_id":"e"*32,"epoch":EPOCH}
        with patch("gway_remote.node_exec_protocol.require_account"), patch("gway_remote.agentops_coordination.node_exchange",return_value={"ok":True}) as call:
            with self.assertRaises(PermissionError):
                serve_one(json.dumps(req).encode(),hostname=NODES[0],trusted_relay=False)
            call.assert_not_called()
            self.assertEqual(serve_one(json.dumps(req).encode(),hostname=NODES[0],trusted_relay=True)["result"],{"ok":True})
            call.assert_called_once_with(NODES[0],req)
            with self.assertRaises(ValueError):
                serve_one(json.dumps({**req,"command":"anything"}).encode(),hostname=NODES[0],trusted_relay=True)

    def test_wire_correlation_and_bound_input(self):
        transport=Mock()
        transport.invoke.return_value={"node":NODES[1],"request_id":"0"*32,"result":{}}
        with self.assertRaises(ValueError):
            c.exchange(transport,NODES[0],EPOCH,"agentops_coordination_snapshot")
        with self.assertRaises(ValueError):
            c.exchange(transport,NODES[0],EPOCH,"agentops_coordination_apply",[{"command":"x"}])
