"""Host identity rotation follows a single authorized Watchtower transition."""
import base64
import os
from datetime import datetime, timedelta, timezone

import pytest
from gway_remote.host_identity import HostIdentityError
from gway_remote.host_trust import rotate_from_snapshot

HEADER = bytes((0,0,0,11)) + b"ssh-ed25519" + bytes((0,0,0,32))
OLD = "ssh-ed25519 " + base64.b64encode(HEADER + bytes(range(32))).decode()
NEW = "ssh-ed25519 " + base64.b64encode(HEADER + bytes(range(1,33))).decode()
WG = base64.b64encode(bytes(range(32))).decode()


def snapshot(now):
    return {"schema": 2, "generated_at": now.isoformat(), "nodes": [{
        "node": "gway-004", "state": "active", "address": "10.90.0.4/32",
        "wireguard_identity": WG, "host_identity": {
            "schema": 1, "node": "gway-004", "wireguard_identity": WG,
            "host_public_key": NEW, "enrollment_binding": "a" * 64,
            "state": "active", "rotation_state": "stable",
            "created_at": (now-timedelta(minutes=1)).isoformat(),
            "valid_until": (now+timedelta(days=1)).isoformat(),
            "rotation": {"previous_host_public_key": OLD,
                         "next_host_public_key": NEW,
                         "authorized_at": (now-timedelta(minutes=1)).isoformat()}
        }
    }]}


def test_rotation_requires_approval_and_matching_old_pin(tmp_path, monkeypatch):
    monkeypatch.setattr("gway_remote.inspection_ssh_trust._trusted_parent_directories", lambda _: None)
    now = datetime.now(timezone.utc)
    path = tmp_path / "known_hosts"
    path.write_text("gway-inspection-gway-004 " + OLD + "\n")
    os.chmod(path, 0o600)
    s = snapshot(now)
    with pytest.raises(HostIdentityError):
        rotate_from_snapshot(s, "gway-004", {"gway-004"}, path, now=now)
    assert OLD in path.read_text()
    assert rotate_from_snapshot(s, "gway-004", {"gway-004"}, path,
                                authorize_rotation=True, now=now)
    assert NEW in path.read_text()
    with pytest.raises(HostIdentityError):
        rotate_from_snapshot(s, "gway-004", {"gway-004"}, path,
                             authorize_rotation=True, now=now)
    s["nodes"][0]["host_identity"]["rotation"]["previous_host_public_key"] = NEW
    with pytest.raises(HostIdentityError):
        rotate_from_snapshot(s, "gway-004", {"gway-004"}, path,
                             authorize_rotation=True, now=now)
