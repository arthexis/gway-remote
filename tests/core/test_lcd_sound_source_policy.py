"""Contract tests for source-bound, per-host LCD/Sound authorization."""
from datetime import datetime, timedelta, timezone
import unittest

from gway_remote.lcd_sound_source_policy import authorize
from gway_remote.lcd_sound_event import validate


def event(origin="ocpp-abb-1", node="gway-001", device="sound",
          action="play", arguments=None):
    return {"schema": 1, "origin": origin, "node": node,
            "request_id": "12" * 16,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat(),
            "device": device, "action": action,
            "arguments": {"name": "notice"} if arguments is None else arguments,
            "hops": 0}


def grants():
    return {
        "oauth:abb-service": {
            "source": "ocpp-abb-1", "targets": ["gway-001"],
            "operations": ["sound.play", "sound.status", "lcd.show", "lcd.status"],
            "enabled": True},
        "oauth:gelectriic-service": {
            "source": "gelectriic.com", "targets": ["gway-001"],
            "operations": ["sound.play", "lcd.status"], "enabled": True}
    }


class SourcePolicyTests(unittest.TestCase):
    def test_each_host_is_bound_to_its_own_authenticated_principal(self):
        one = authorize(event(), verified_principal="oauth:abb-service", grants=grants())
        self.assertEqual(one["source"], "ocpp-abb-1")
        two = authorize(event(origin="gelectriic.com"),
                        verified_principal="oauth:gelectriic-service", grants=grants())
        self.assertEqual(two["source"], "gelectriic.com")

    def test_default_receiver_still_rejects_untrusted_external_source(self):
        with self.assertRaises(PermissionError):
            validate(event(), trusted_node="gway-001")

    def test_spoofed_host_and_wrong_principal_rejected(self):
        for principal in ("oauth:gelectriic-service", "oauth:unknown", "",
                          "ocpp-abb-1"):
            with self.subTest(principal=principal), self.assertRaises(PermissionError):
                authorize(event(), verified_principal=principal, grants=grants())

    def test_revocation_is_immediate(self):
        policy = grants()
        policy["oauth:abb-service"]["enabled"] = False
        with self.assertRaises(PermissionError):
            authorize(event(), verified_principal="oauth:abb-service", grants=policy)

    def test_targets_and_operations_are_scoped(self):
        for e in (event(node="gway-002"), event(device="sound", action="mute", arguments={}),
                  event(origin="watchtower")):
            with self.subTest(e=e), self.assertRaises(PermissionError):
                authorize(e, verified_principal="oauth:abb-service", grants=grants())

    def test_tampering_expiry_and_loops_rejected(self):
        for change in ({"hops": 1}, {"request_id": "bad"},
                       {"expires_at": "2000-01-01T00:00:00+00:00"},
                       {"arguments": {"name": "unsafe;id"}}):
            e = event()
            e.update(change)
            with self.subTest(change=change), self.assertRaises((PermissionError, ValueError)):
                authorize(e, verified_principal="oauth:abb-service", grants=grants())

    def test_malformed_source_grants_fail_closed(self):
        for change in ({"targets": ["gway-001", "gway-001"]},
                       {"targets": ["*"]}, {"operations": ["exec.shell"]},
                       {"source": "watchtower"}, {"enabled": "true"},
                       {"operations": []}):
            policy = grants()
            policy["oauth:abb-service"].update(change)
            with self.subTest(change=change), self.assertRaises(PermissionError):
                authorize(event(), verified_principal="oauth:abb-service", grants=policy)
