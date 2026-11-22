"""Hermetic node receiver contracts: no actual LCD, audio or network."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from gway_remote import lcd_sound_event as m


def event(action="play", arguments=None, device="sound", **changes):
    result = {
        "schema": 1, "node": "gway-001", "origin": "watchtower",
        "request_id": "ab" * 16,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat(),
        "device": device, "action": action,
        "arguments": arguments if arguments is not None else {"name": "notice"},
        "hops": 0,
    }
    result.update(changes)
    return result


@pytest.fixture
def journal(tmp_path):
    root = tmp_path / "private"
    root.mkdir()
    root.chmod(0o700)
    return root / "events.sqlite3"


def test_sound_dispatch_only_once(journal):
    calls = []
    def runner(argv, **kw):
        calls.append((argv, kw))
        return SimpleNamespace(returncode=0)
    payload = event()
    first = m.receive(payload, trusted_node="gway-001", db_path=journal, run=runner)
    second = m.receive(payload, trusted_node="gway-001", db_path=journal, run=runner)
    assert first == {"status": "succeeded", "duplicate": False}
    assert second == {"status": "succeeded", "duplicate": True}
    assert len(calls) == 1
    assert calls[0][0] == ["gway-lcd-sound", "sound", "play", "notice"]
    assert calls[0][1]["env"]["GWAY_LCD_SOUND_FORCE_LOCAL"] == "1"
    assert journal.stat().st_mode & 0o777 == 0o600


def test_different_payload_same_id_denied(journal):
    runner = lambda *a, **kw: SimpleNamespace(returncode=0)
    m.receive(event(), trusted_node="gway-001", db_path=journal, run=runner)
    with pytest.raises(PermissionError, match="reused"):
        m.receive(event(arguments={"name": "error"}), trusted_node="gway-001", db_path=journal, run=runner)


def test_ambiguous_delivery_never_replayed(journal):
    calls = []
    def failing(*a, **kw):
        calls.append(1)
        raise OSError("offline")
    payload = event()
    assert m.receive(payload, trusted_node="gway-001", db_path=journal, run=failing)["status"] == "uncertain"
    assert m.receive(payload, trusted_node="gway-001", db_path=journal, run=failing)["duplicate"]
    assert len(calls) == 1


def test_receiving_node_identity_and_no_relay():
    with pytest.raises(PermissionError):
        m.validate(event(node="gway-002"), trusted_node="gway-001")
    with pytest.raises(PermissionError):
        m.validate(event(hops=1), trusted_node="gway-001")
    with pytest.raises(PermissionError):
        m.validate(event(origin="gway-001"), trusted_node="gway-001")


@pytest.mark.parametrize("alteration", [
    {"expires_at": "1999-01-01T00:00:00+00:00"},
    {"expires_at": "2100-01-01T00:00:00+00:00"},
    {"request_id": "not-a-uuid"},
    {"hops": False},
    {"device": "exec"},
    {"action": "shell"},
    {"origin": "../outside"},
    {"arguments": {"name": "warning; sh -c id"}},
    {"arguments": {"name": "notice", "extra": "bad"}},
])
def test_rejects_untrusted_envelopes(alteration):
    with pytest.raises((ValueError, PermissionError)):
        m.validate(event(**alteration), trusted_node="gway-001")


def test_lcd_priority_is_left_to_local_owner(journal):
    calls = []
    def runner(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0)
    payload = event(device="lcd", action="show",
                    arguments={"line1": "Watchtower", "line2": "Ready", "seconds": 20})
    assert m.receive(payload, trusted_node="gway-001", db_path=journal, run=runner)["status"] == "succeeded"
    assert calls == [["gway-lcd-sound", "lcd", "show", "Watchtower", "Ready", "--seconds", "20"]]


def test_sound_event_preserves_receiver_mapping_and_within():
    payload = event(action="event", arguments={"event": "deploy-verified", "source": "gway-remote", "within": 30})
    m.validate(payload, trusted_node="gway-001")
    assert m.argv_for(payload) == ["sound", "--event", "deploy-verified", "--source", "gway-remote", "--within", "30"]


def test_sequence_validation():
    seq = json.dumps({"format": "gway-piano-v1", "notes": [[440, 0.1, 0.0]]})
    m.validate(event(action="sequence", arguments={"sequence": seq}), trusted_node="gway-001")
    with pytest.raises(ValueError):
        m.validate(event(action="sequence", arguments={"sequence": '{"format":"gway-piano-v1","notes":[[5000,1,0]]}'}), trusted_node="gway-001")


def test_refuses_world_readable_journal(journal):
    journal.write_bytes(b"")
    journal.chmod(0o644)
    with pytest.raises(PermissionError):
        m.receive(event(), trusted_node="gway-001", db_path=journal)
