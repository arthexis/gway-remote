"""Hermetic per-source authorization and fixed-argv notice transport."""
from datetime import datetime, timedelta, timezone
import json
import pytest

from gway_remote.lcd_sound_event import validate, argv_for
from gway_remote.lcd_sound_source_policy import authorize
from gway_remote.lcd_notification_contract import validate_notice

NOW = datetime(2026, 11, 24, 7, tzinfo=timezone.utc)
PRINCIPAL = "a1"*12


def notice(**changes):
    return dict({
        "schema": "gway-notification/v1",
        "system": "fleet", "origin_node": "gelectriic.com",
        "target_node": "ocpp-abb-1",
        "subject": {"type": "service", "name": "ocpp-reports"},
        "state": "down", "severity": "critical",
        "reason_code": "SERVICE_DOWN", "episode_id": "fleet-abc",
        "expires_in": 120,
    }, **changes)


def event(document=None):
    return {"schema": 1, "node": "gway-001", "origin": "gelectriic.com",
            "request_id": "ab"*16,
            "expires_at": (NOW + timedelta(seconds=20)).isoformat(),
            "device": "lcd", "action": "notice",
            "arguments": {"notice": notice() if document is None else document},
            "hops": 0}


def grants():
    return {PRINCIPAL: {"source": "gelectriic.com", "targets": ["gway-001"],
                        "operations": ["lcd.notice"], "enabled": True}}


def test_authorized_notice_is_validated_and_non_shell():
    e = event()
    authorize(e, verified_principal=PRINCIPAL, grants=grants())
    validate(e, trusted_node="gway-001", trusted_origin="gelectriic.com", now=NOW)
    cmd = argv_for(e)
    assert cmd[:3] == ["gway-lcd-sound", "lcd", "notice"]
    assert json.loads(cmd[3]) == notice()


def test_identity_cannot_be_forged_by_sender_body():
    e = event(notice(origin_node="ocpp-abb-1"))
    with pytest.raises(PermissionError, match="origin"):
        authorize(e, verified_principal=PRINCIPAL, grants=grants())


def test_new_operation_requires_explicit_grant():
    g = grants()
    g[PRINCIPAL]["operations"] = ["lcd.show", "sound.play"]
    with pytest.raises(PermissionError):
        authorize(event(), verified_principal=PRINCIPAL, grants=g)


@pytest.mark.parametrize("bad", [
    {"state": "code"}, {"severity": "info"},
    {"reason_code": "../../secrets"}, {"episode_id": "spaces not allowed"},
    {"target_node": "gway-001 && whoami"}, {"expires_in": 1000},
    {"subject": {"type": "repository", "repository": "arthexis/gway-remote"}},
])
def test_reject_untrusted_notice_content(bad):
    with pytest.raises(ValueError):
        validate_notice(notice(**bad))
