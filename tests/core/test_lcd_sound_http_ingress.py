"""Loopback-only opt-in HTTP ingress regression; no SSH, network peers or hardware."""
from datetime import datetime, timedelta, timezone
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.mcp_bearer_gateway import make_server


def event(source="ocpp-abb-1"):
    return {"schema": 1, "node": "gway-001", "origin": source,
            "request_id": "ac" * 16,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat(),
            "device": "sound", "action": "play",
            "arguments": {"name": "notice"}, "hops": 0}


class LCDSoundHttpIngressTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "registry.db"
        self.registry = BearerRegistry(path)
        self.verifier = BearerVerifier(path)
        self.abb = self.registry.issue(scope="gway:lcd-sound", operator_approved=True)
        self.website = self.registry.issue(scope="gway:lcd-sound", operator_approved=True)
        self.abb_id = self.verifier.lcd_sound_principal(self.abb)
        self.website_id = self.verifier.lcd_sound_principal(self.website)
        self.grants = {
            self.abb_id: {"source": "ocpp-abb-1", "targets": ["gway-001"],
                          "operations": ["sound.play"], "enabled": True},
            self.website_id: {"source": "gelectriic.com", "targets": ["gway-001"],
                              "operations": ["sound.play"], "enabled": True}}
        self.received = []
        self.reply_status = "succeeded"

    def server(self, *, enabled):
        def relay(request):
            self.received.append(request)
            return {"node": request["node"], "request_id": request["request_id"],
                    "status": self.reply_status}
        httpd = make_server(("127.0.0.1", 0), self.verifier,
                            "http://127.0.0.1:19011/mcp", "unused-test-backend-token",
                            lcd_sound_ingress_enabled=enabled, lcd_sound_dispatch=relay,
                            lcd_sound_grants_loader=lambda: self.grants)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return httpd.server_address[1]

    def post(self, port, data, bearer, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
        self.addCleanup(conn.close)
        h = {"Authorization": "Bearer " + bearer, "Content-Type": "application/json"}
        if headers:
            h.update(headers)
        conn.request("POST", "/v1/lcd-sound/event", json.dumps(data), h)
        result = conn.getresponse()
        return result.status, result.read()

    def test_default_gateway_does_not_expose_event_route(self):
        port = self.server(enabled=False)
        self.assertEqual(self.post(port, event(), self.abb)[0], 404)
        self.assertEqual(self.received, [])

    def test_two_bearers_have_distinct_receiver_identity(self):
        port = self.server(enabled=True)
        a, body_a = self.post(port, event(), self.abb)
        b, body_b = self.post(port, event("gelectriic.com"), self.website)
        self.assertEqual((a, b), (200, 200))
        self.assertEqual(len(self.received), 2)
        self.assertTrue(all(e["origin"] == "watchtower" for e in self.received))
        self.assertNotEqual(self.received[0]["request_id"], self.received[1]["request_id"])
        self.assertEqual(json.loads(body_a)["source"], "ocpp-abb-1")
        self.assertEqual(json.loads(body_b)["source"], "gelectriic.com")

    def test_general_mcp_execute_bearer_has_no_source_authority(self):
        port = self.server(enabled=True)
        broad = self.registry.issue(scope="gway:execute", operator_approved=True)
        self.assertEqual(self.post(port, event(), broad)[0], 403)
        self.assertEqual(self.received, [])

    def test_source_only_bearer_cannot_call_general_mcp(self):
        port = self.server(enabled=True)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
        self.addCleanup(conn.close)
        rpc = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        conn.request("POST", "/mcp", rpc, {
            "Authorization": "Bearer " + self.abb,
            "Content-Type": "application/json"})
        response = conn.getresponse()
        self.assertEqual(response.status, 401)
        response.read()
        self.assertEqual(self.received, [])

    def test_cross_host_spoof_and_revocation_denied(self):
        port = self.server(enabled=True)
        self.assertEqual(self.post(port, event("gelectriic.com"), self.abb)[0], 403)
        self.assertTrue(self.registry.revoke(self.abb_id))
        self.assertEqual(self.post(port, event(), self.abb)[0], 403)
        self.grants[self.website_id]["enabled"] = False
        self.assertEqual(self.post(port, event("gelectriic.com"), self.website)[0], 403)
        self.assertEqual(self.received, [])

    def test_origin_header_is_not_source_authentication(self):
        port = self.server(enabled=True)
        self.assertEqual(self.post(port, event(), self.abb, {"Origin": "ocpp-abb-1"})[0], 403)
        self.assertFalse(self.received)

    def test_uncertain_is_reported_not_replayed(self):
        self.reply_status = "uncertain"
        port = self.server(enabled=True)
        status, data = self.post(port, event(), self.abb)
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(data)["status"], "uncertain")
        self.assertEqual(len(self.received), 1)
