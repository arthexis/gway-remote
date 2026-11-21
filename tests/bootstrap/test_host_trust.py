"""Offline trust pin lifecycle tests: no SSH or GPIO."""
import base64
import os
from datetime import datetime, timedelta, timezone

import pytest

from gway_remote.host_identity import HostIdentityError
from gway_remote.host_trust import pin_from_snapshot


def fixture(now):
    host = bytes((0, 0, 0, 11)) + b"ssh-ed25519" + bytes((0, 0, 0, 32)) + bytes(range(32))
    wg = base64.b64encode(bytes(range(32))).decode()
    identity = {
        "schema": 1, "node": "gway-004", "state": "active",
        "rotation_state": "stable", "enrollment_binding": "a" * 64,
        "wireguard_identity": wg,
        "host_public_key": "ssh-ed25519 " + base64.b64encode(host).decode(),
        "created_at": (now - timedelta(hours=1)).isoformat(),
        "valid_until": (now + timedelta(days=1)).isoformat(),
    }
    return {"schema": 2, "generated_at": now.isoformat(), "nodes": [
        {"node": "gway-004", "state": "active", "address": "10.90.0.4/32",
         "wireguard_identity": wg, "host_identity": identity}
    ]}


def test_explicit_first_pin_idempotent_and_no_rotation(tmp_path, monkeypatch):
    monkeypatch.setattr('gway_remote.inspection_ssh_trust._trusted_parent_directories', lambda path: None)
    now = datetime.now(timezone.utc)
    snapshot = fixture(now)
    path = tmp_path / "known_hosts"
    path.write_text("")
    os.chmod(path, 0o600)
    with pytest.raises(HostIdentityError):
        pin_from_snapshot(snapshot, "gway-004", {"gway-004"}, path, now=now)
    assert path.read_text() == ""
    assert pin_from_snapshot(snapshot, "gway-004", {"gway-004"}, path,
                             authorize_initial=True, now=now)
    assert not pin_from_snapshot(snapshot, "gway-004", {"gway-004"}, path, now=now)
    old = path.read_text()
    snapshot["nodes"][0]["host_identity"]["host_public_key"] = (
        "ssh-ed25519 " + base64.b64encode(
            bytes((0, 0, 0, 11)) + b"ssh-ed25519" +
            bytes((0, 0, 0, 32)) + bytes([1] * 32)).decode())
    with pytest.raises(HostIdentityError):
        pin_from_snapshot(snapshot, "gway-004", {"gway-004"}, path,
                          authorize_initial=True, now=now)
    assert path.read_text() == old


def test_binding_revocation_and_permissions_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr('gway_remote.inspection_ssh_trust._trusted_parent_directories', lambda path: None)
    now = datetime.now(timezone.utc)
    snapshot = fixture(now)
    path = tmp_path / "known_hosts"
    path.write_text("")
    os.chmod(path, 0o644)
    with pytest.raises(HostIdentityError):
        pin_from_snapshot(snapshot, "gway-004", {"gway-004"}, path,
                          authorize_initial=True, now=now)
    os.chmod(path, 0o600)
    snapshot["nodes"][0]["wireguard_identity"] = "absent"
    with pytest.raises(HostIdentityError):
        pin_from_snapshot(snapshot, "gway-004", {"gway-004"}, path,
                          authorize_initial=True, now=now)
    snapshot = fixture(now)
    snapshot["nodes"][0]["host_identity"]["state"] = "revoked"
    with pytest.raises(HostIdentityError):
        pin_from_snapshot(snapshot, "gway-004", {"gway-004"}, path,
                          authorize_initial=True, now=now)
    assert path.read_text() == ""
