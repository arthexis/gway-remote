"""Real local BearerVerifier source-binding tests; no network or hardware."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from gway_remote.mcp_bearer import BearerRegistry, BearerVerifier
from gway_remote.lcd_sound_ingress import forward_verified_bearer


def event(source="ocpp-abb-1"):
    return {
        "schema": 1, "node": "gway-001", "origin": source,
        "request_id": "ab" * 16,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat(),
        "device": "sound", "action": "play", "arguments": {"name": "notice"},
        "hops": 0
    }


class VerifiedBearerIngressTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "bearers.db"
        self.registry = BearerRegistry(path)
        self.verifier = BearerVerifier(path)
        self.first = self.registry.issue(scope="gway:lcd-sound", operator_approved=True)
        self.second = self.registry.issue(scope="gway:lcd-sound", operator_approved=True)
        self.principal_one = self.verifier.lcd_sound_principal(self.first)
        self.principal_two = self.verifier.lcd_sound_principal(self.second)
        self.grants = {
            self.principal_one: {
                "source": "ocpp-abb-1", "targets": ["gway-001"],
                "operations": ["sound.play"], "enabled": True},
            self.principal_two: {
                "source": "gelectriic.com", "targets": ["gway-001"],
                "operations": ["sound.play"], "enabled": True}
        }

    def forward(self, data, bearer):
        seen = []
        def relay(request):
            seen.append(request)
            return {"node": request["node"], "request_id": request["request_id"],
                    "status": "succeeded"}
        response = forward_verified_bearer(data, bearer=bearer,
                                           verifier=self.verifier,
                                           load_grants=lambda: self.grants,
                                           dispatch=relay)
        return response, seen

    def test_dedicated_source_credential_cannot_read_or_execute_mcp_tools(self):
        self.assertFalse(self.verifier.verify(self.first, required_scope="gway:read"))
        self.assertFalse(self.verifier.verify(self.first, required_scope="gway:execute"))
        with self.assertRaises(PermissionError):
            self.verifier.execution_principal(self.first)

    def test_independent_token_proves_each_host(self):
        one, a = self.forward(event(), self.first)
        two, b = self.forward(event("gelectriic.com"), self.second)
        self.assertEqual(one["source"], "ocpp-abb-1")
        self.assertEqual(two["source"], "gelectriic.com")
        self.assertNotEqual(one["receiver_request_id"], two["receiver_request_id"])
        self.assertEqual(a[0]["origin"], "watchtower")
        self.assertEqual(b[0]["origin"], "watchtower")

    def test_cross_host_spoofing_rejected(self):
        with self.assertRaises(PermissionError):
            self.forward(event("gelectriic.com"), self.first)

    def test_bearer_revocation_denies_before_relay(self):
        self.assertTrue(self.registry.revoke(self.principal_one))
        with self.assertRaises(PermissionError):
            self.forward(event(), self.first)

    def test_grant_revocation_denies_before_relay(self):
        self.grants[self.principal_one]["enabled"] = False
        with self.assertRaises(PermissionError):
            self.forward(event(), self.first)

    def test_missing_or_read_scope_bearer_rejected(self):
        token = self.registry.issue(scope="gway:read")
        broad = self.registry.issue(scope="gway:execute", operator_approved=True)
        combined = self.registry.issue_combined(operator_approved=True)
        for bearer in (token, broad, combined, "", "bad"):
            with self.subTest(bearer=bearer[:8]), self.assertRaises(PermissionError):
                self.forward(event(), bearer)

    def test_delegated_source_token_uses_stable_parent_identity(self):
        delegate = self.registry.issue(scope="gway:lcd-sound", parent_id=self.principal_one)
        self.assertEqual(self.verifier.lcd_sound_principal(delegate), self.principal_one)
        response, _ = self.forward(event(), delegate)
        self.assertEqual(response["source"], "ocpp-abb-1")
        self.registry.revoke(self.principal_one)
        with self.assertRaises(PermissionError):
            self.forward(event(), delegate)
