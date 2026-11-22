"""Hermetic Watchtower sender identity and bounded transport tests."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from gway_remote import lcd_sound_bridge as bridge
from gway_remote.watchtower_exec_transport import SSHTransportFailure


def payload():
    return {
        "schema": 1, "node": "gway-001", "origin": "watchtower",
        "request_id": "ab" * 16,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat(),
        "device": "sound", "action": "play", "arguments": {"name": "notice"},
        "hops": 0,
    }


def inventory(eligible=True):
    return {"nodes": [{"node": "gway-001", "registered": True,
                       "identity_verified": True, "execute_eligible": eligible,
                       "reachable": "reachable"}]}


class PinnedBridgeTests(TestCase):
    def test_retry_uses_identical_request_id(self):
        calls = []
        class Transport:
            def invoke(self, req):
                calls.append(req)
                if len(calls) == 1:
                    raise SSHTransportFailure("lost acknowledgement")
                return {"node": "gway-001", "request_id": req["request_id"],
                        "result": {"status": "succeeded", "duplicate": True}}
        service = SimpleNamespace(relay=SimpleNamespace(transport=Transport()))
        with patch("gway_remote.node_registry_inventory.load", return_value=inventory()):
            result = bridge.dispatch(payload(), load=lambda: service, sleep=lambda _: None)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(len(calls), 2)

    def test_revoked_node_never_contacts_transport(self):
        calls = []
        class Transport:
            def invoke(self, req):
                calls.append(req)
        service = SimpleNamespace(relay=SimpleNamespace(transport=Transport()))
        with patch("gway_remote.node_registry_inventory.load", return_value=inventory(False)):
            with self.assertRaises(PermissionError):
                bridge.dispatch(payload(), load=lambda: service)
        self.assertEqual(calls, [])

    def test_sender_origin_cannot_be_spoofed(self):
        event = payload()
        event["origin"] = "gway-005"
        service = SimpleNamespace(relay=SimpleNamespace(transport=object()))
        with patch("gway_remote.node_registry_inventory.load", return_value=inventory()):
            with self.assertRaises(PermissionError):
                bridge.dispatch(event, load=lambda: service)

    def test_uncorrelated_ssh_response_rejected(self):
        class Transport:
            def invoke(self, req):
                return {"node": "gway-001", "request_id": req["request_id"],
                        "result": {"status": "unknown"}}
        service = SimpleNamespace(relay=SimpleNamespace(transport=Transport()))
        with patch("gway_remote.node_registry_inventory.load", return_value=inventory()):
            with self.assertRaises(RuntimeError):
                bridge.dispatch(payload(), load=lambda: service)

    def test_verified_probe_uses_existing_limits_operation(self):
        class Transport:
            def invoke(self, req):
                self.req = req
                return {"node": req["node"], "request_id": req["request_id"],
                        "concurrent_jobs_per_node": 1}
        transport = Transport()
        service = SimpleNamespace(relay=SimpleNamespace(transport=transport))
        with patch("gway_remote.node_registry_inventory.load", return_value=inventory()):
            result = bridge.probe("gway-001", load=lambda: service)
        self.assertEqual(result["transport"], "pinned_ssh")
        self.assertEqual(transport.req["operation"], "limits")
