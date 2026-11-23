"""Standalone allowed Reports action validation (no transport or GPIO)."""
from datetime import datetime, timedelta, timezone
import json
import pytest
from gway_remote.lcd_sound_event import validate, argv_for


NOW = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)


def event(frames):
    return {"schema": 1, "node": "gway-001", "origin": "watchtower",
            "request_id": "ab"*16, "expires_at": (NOW + timedelta(seconds=20)).isoformat(),
            "device": "lcd", "action": "reports", "arguments": {"frames": frames}, "hops": 0}


def sample():
    return {"id": "ab"*12, "line1": "P Monterrey 037m", "line2": "Charging 78%"}


def test_valid_report_command_is_non_shell_json():
    doc = event([sample()])
    validate(doc, trusted_node="gway-001", now=NOW)
    argv = argv_for(doc)
    assert argv[:3] == ["gway-lcd-sound", "lcd", "reports"]
    assert json.loads(argv[3]) == [sample()]


@pytest.mark.parametrize("frames", [
    [{"id": "../tmp", "line1": "A", "line2": "B"}],
    [{**sample(), "line1": "X"*17}],
    [{**sample(), "line2": "X\nB"}],
    [sample(), sample()],
    [sample()]*17,
    [{**sample(), "until": "2025-01-01T00:00:00+00:00"}],
])
def test_invalid_reports_rejected(frames):
    with pytest.raises((ValueError, PermissionError)):
        validate(event(frames), trusted_node="gway-001", now=NOW)


def test_wrong_origin_denied():
    doc = event([sample()])
    doc["origin"] = "ocpp-abb-1"
    with pytest.raises(PermissionError):
        validate(doc, trusted_node="gway-001", now=NOW)
