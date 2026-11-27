import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from gway_remote.mcp_owner_bound_wire import make_payload,validate,reserve
from gway_remote.node_exec_protocol import serve_one
from gway_remote.mcp_provider_transport import ProviderTransport
from gway_remote.watchtower_exec_transport import SSHTransport

NODE="gway-001"
P="a"*24
RID="b"*32
REQ={"provider":"aeon_score","tool":"status","arguments":{"key":"c"*32}}

class OwnerWireTests(unittest.TestCase):
    def test_pinned_sender_correlates_and_binds(self):
        def send(argv,*,input,**kwargs):
            req=json.loads(input)
            self.assertEqual(req["principal"],P)
            self.assertEqual(validate(req,NODE),"read")
            self.assertIn("StrictHostKeyChecking=yes",argv)
            return SimpleNamespace(stdout=json.dumps({"node":NODE,"request_id":req["request_id"],"result":{"ok":True}}).encode())
        node=SimpleNamespace(node=NODE,known_hosts="/tmp/kh",ssh_host_alias=NODE,
            identity_file="/tmp/key",remote_user="gway-relay",wireguard_address="10.90.0.2")
        client=ProviderTransport(SSHTransport(node,run=send))
        self.assertEqual(client.invoke_principal(NODE,REQ,trusted_scope="read",verified_principal=P),{"ok":True})

    def test_tampering_and_expiration(self):
        req=make_payload(NODE,REQ,"read",P,RID,now=1000)
        for altered in ({**req,"arguments":{"key":"d"*32}},
                        {**req,"node":"gway-002"},
                        {**req,"provider":"odoo"},
                        {**req,"principal":"invalid"},
                        {**req,"scope":"execute"}):
            with self.assertRaises((ValueError,PermissionError)):
                validate(altered,NODE,now=1000)
        with self.assertRaises(PermissionError):
            validate(req,NODE,now=1091)
        with self.assertRaises(PermissionError):
            validate(req,NODE,now=994)

    def test_durable_replay_and_bounded_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            req=make_payload(NODE,REQ,"read",P,RID,now=1000)
            reserve(req,directory=tmp,now=1000)
            with self.assertRaisesRegex(PermissionError,"replayed"):
                reserve(req,directory=tmp,now=1001)
            other=make_payload(NODE,REQ,"read",P,"d"*32,now=1001)
            with patch("gway_remote.mcp_owner_bound_wire.CAP",1):
                with self.assertRaisesRegex(PermissionError,"capacity"):
                    reserve(other,directory=tmp,now=1001)
                later=make_payload(NODE,REQ,"read",P,"e"*32,now=1092)
                reserve(later,directory=tmp,now=1092)
            with self.assertRaises(PermissionError):
                reserve(req,directory=tmp,now=1092)

    def test_receiver_requires_relay_and_passes_scope(self):
        req=make_payload(NODE,REQ,"read",P,RID)
        with patch("gway_remote.node_exec_protocol.require_account"), \
             patch("gway_remote.mcp_owner_bound_wire.reserve") as reserve_spy, \
             patch("gway_remote.mcp_installed_providers.discover_installed_providers",return_value=[]) as discovery, \
             patch("gway_remote.mcp_node_providers.provider_call",return_value={"content":[]}) as call:
            with self.assertRaises(PermissionError):
                serve_one(json.dumps(req).encode(),hostname=NODE)
            discovery.assert_not_called()
            serve_one(json.dumps(req).encode(),hostname=NODE,trusted_relay=True)
            reserve_spy.assert_called_once_with(req)
            call.assert_called_once_with([],provider="aeon_score",tool="status",
                arguments=REQ["arguments"],authorized_scope="read",verified_principal=P)
