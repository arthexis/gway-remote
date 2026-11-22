"""Hermetic authenticated ingress / pinned relay integration contracts."""
from datetime import datetime, timedelta, timezone
import unittest

from gway_remote.lcd_sound_ingress import forward_authenticated


def sample(source="ocpp-abb-1", request_id="cd" * 16):
    return {
        "schema": 1, "origin": source, "node": "gway-001",
        "request_id": request_id,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat(),
        "device": "sound", "action": "play", "arguments": {"name": "notice"},
        "hops": 0
    }


def policy():
    return {
        "auth:ocpp-abb-1": {"source": "ocpp-abb-1",
                            "targets": ["gway-001"], "operations": ["sound.play"],
                            "enabled": True},
        "auth:gelectriic.com": {"source": "gelectriic.com",
                                "targets": ["gway-001"], "operations": ["sound.play"],
                                "enabled": True},
    }


class AuthenticatedIngressTests(unittest.TestCase):
    def test_both_sources_relay_as_watchtower_but_retain_source_receipt(self):
        for source, principal in (("ocpp-abb-1", "auth:ocpp-abb-1"),
                                  ("gelectriic.com", "auth:gelectriic.com")):
            with self.subTest(source=source):
                seen = []
                def bridge(event):
                    seen.append(event)
                    return {"node": "gway-001", "request_id": event["request_id"],
                            "status": "succeeded", "duplicate": False}
                original = sample(source)
                result = forward_authenticated(original, authenticated_principal=principal,
                                               operator_grants=policy(), dispatch=bridge)
                self.assertEqual(seen[0]["origin"], "watchtower")
                self.assertNotEqual(seen[0]["request_id"], original["request_id"])
                self.assertEqual(result["receiver_request_id"], seen[0]["request_id"])
                self.assertEqual(result["request_id"], original["request_id"])
                self.assertEqual(original["origin"], source)
                self.assertEqual(result["source"], source)
                self.assertEqual(len(result["source_event_sha256"]), 64)

    def test_distinct_source_ids_cannot_collide_in_receiver_journal(self):
        ids = []
        for origin, principal in (("ocpp-abb-1", "auth:ocpp-abb-1"),
                                  ("gelectriic.com", "auth:gelectriic.com"),
                                  ("ocpp-abb-1", "auth:ocpp-abb-1")):
            def relay(event):
                ids.append(event["request_id"])
                return {"node": event["node"], "request_id": event["request_id"],
                        "status": "succeeded"}
            forward_authenticated(sample(origin), authenticated_principal=principal,
                                  operator_grants=policy(), dispatch=relay)
        self.assertNotEqual(ids[0], ids[1])
        self.assertEqual(ids[0], ids[2])

    def test_spoofing_and_revocation_do_not_invoke_pinned_transport(self):
        calls = []
        bridge = lambda data: calls.append(data)
        for event, principal, grants in (
            (sample("ocpp-abb-1"), "auth:gelectriic.com", policy()),
            (sample("ocpp-abb-1"), "unknown", policy()),
            (sample("ocpp-abb-1"), "auth:ocpp-abb-1", {
                **policy(), "auth:ocpp-abb-1": {
                    **policy()["auth:ocpp-abb-1"], "enabled": False}}),
            (sample("watchtower"), "auth:ocpp-abb-1", policy()),
            (sample("ocpp-abb-1", request_id="bad"), "auth:ocpp-abb-1", policy()),
        ):
            with self.subTest(origin=event["origin"], principal=principal):
                with self.assertRaises((PermissionError, ValueError)):
                    forward_authenticated(event, authenticated_principal=principal,
                                          operator_grants=grants, dispatch=bridge)
        self.assertEqual(calls, [])

    def test_uncertain_result_not_retried_or_locally_fallback(self):
        events = []
        def bridge(event):
            events.append(event)
            return {"node": event["node"], "request_id": event["request_id"],
                    "status": "uncertain"}
        answer = forward_authenticated(sample(), authenticated_principal="auth:ocpp-abb-1",
                                       operator_grants=policy(), dispatch=bridge)
        self.assertEqual(answer["status"], "uncertain")
        self.assertEqual(len(events), 1)

    def test_mismatched_acknowledgment_is_rejected(self):
        with self.assertRaises(RuntimeError):
            forward_authenticated(sample(), authenticated_principal="auth:ocpp-abb-1",
                                  operator_grants=policy(),
                                  dispatch=lambda x: {"node": "gway-002",
                                                      "request_id": x["request_id"],
                                                      "status": "succeeded"})

    def test_reject_expired_message_before_dispatch(self):
        data = sample()
        data["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        calls = []
        with self.assertRaises(ValueError):
            forward_authenticated(data, authenticated_principal="auth:ocpp-abb-1",
                                  operator_grants=policy(), dispatch=lambda e: calls.append(e))
        self.assertFalse(calls)
