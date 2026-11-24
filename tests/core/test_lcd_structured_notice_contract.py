"""Unittest-compatible authenticated, fixed-argv notification transport."""
from datetime import datetime, timedelta, timezone
import json
import unittest

from gway_remote.lcd_sound_event import validate, argv_for
from gway_remote.lcd_sound_source_policy import authorize
from gway_remote.lcd_notification_contract import validate_notice

PRINCIPAL = "a1" * 12


def notice(**changes):
    return dict({
        "schema": "gway-notification/v1", "system": "fleet",
        "origin_node": "gelectriic.com", "target_node": "ocpp-abb-1",
        "subject": {"type": "service", "name": "ocpp-reports"},
        "state": "down", "severity": "critical", "reason_code": "SERVICE_DOWN",
        "episode_id": "fleet-abc", "expires_in": 120,
    }, **changes)


def event(document=None):
    return {"schema": 1, "node": "gway-001", "origin": "gelectriic.com",
            "request_id": "ab" * 16,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat(),
            "device": "lcd", "action": "notice",
            "arguments": {"notice": notice() if document is None else document},
            "hops": 0}


def grants():
    return {PRINCIPAL: {"source": "gelectriic.com", "targets": ["gway-001"],
                        "operations": ["lcd.notice"], "enabled": True}}


class StructuredNoticeAuthorizationTests(unittest.TestCase):
    def test_authorized_notice_uses_a_fixed_non_shell_argv(self):
        e = event()
        authorize(e, verified_principal=PRINCIPAL, grants=grants())
        validate(e, trusted_node="gway-001", trusted_origin="gelectriic.com")
        cmd = argv_for(e)
        self.assertEqual(cmd[:3], ["gway-lcd-sound", "lcd", "notice"])
        self.assertEqual(json.loads(cmd[3]), notice())

    def test_untrusted_sender_cannot_spoof_identity(self):
        with self.assertRaisesRegex(PermissionError, "origin"):
            authorize(event(notice(origin_node="ocpp-abb-1")),
                      verified_principal=PRINCIPAL, grants=grants())

    def test_operation_is_denied_without_explicit_operator_grant(self):
        permitted = grants()
        permitted[PRINCIPAL]["operations"] = ["lcd.show", "sound.play"]
        with self.assertRaises(PermissionError):
            authorize(event(), verified_principal=PRINCIPAL, grants=permitted)

    def test_invalid_notice_data_fail_closed(self):
        for bad in (
            {"state": "code"}, {"severity": "info"}, {"reason_code": "../../secrets"},
            {"episode_id": "spaces not allowed"}, {"target_node": "gway-001 && whoami"},
            {"expires_in": 1000},
            {"subject": {"type": "repository", "repository": "arthexis/gway-remote"}},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_notice(notice(**bad))


if __name__ == "__main__":
    unittest.main()
