"""Cross-component contract: enrollment -> restricted snapshot -> explicit pin."""
import base64
import os

import pytest

from gway_remote.host_identity import HostIdentityError
from gway_remote.host_trust import pin_from_snapshot
from gway_remote.node_inspection import snapshot_from_path
from gway_remote.watchtower_enrollment import Ledger

HEADER = bytes((0, 0, 0, 11)) + b"ssh-ed25519" + bytes((0, 0, 0, 32))
HOST = "ssh-ed25519 " + base64.b64encode(HEADER + bytes(range(32))).decode()
WG = base64.b64encode(bytes(range(32))).decode()


def test_bootstrap_to_restricted_trust_then_revoke(tmp_path, monkeypatch):
    monkeypatch.setattr("gway_remote.inspection_ssh_trust._trusted_parent_directories", lambda _: None)
    ledger = Ledger(tmp_path / "ledger.sqlite3", network="10.90.0.0/24",
                    gateway="10.90.0.1")
    token = ledger.invite("gway-004")["token"]
    enrollment = ledger.reserve(device="gway-004", public_key=WG, token=token,
                                occupied=set(), ssh_host_key=HOST)
    ledger.advance(enrollment.operation_id, "committed")
    snapshot = snapshot_from_path(ledger.path)
    assert snapshot["nodes"][0]["host_identity_status"] == "active"
    path = tmp_path / "known_hosts"
    path.write_text("")
    os.chmod(path, 0o600)
    assert pin_from_snapshot(snapshot, "gway-004", {"gway-004"}, path,
                             authorize_initial=True)
    assert HOST in path.read_text()
    assert ledger.revoke_host_identity("gway-004")
    revoked = snapshot_from_path(ledger.path)
    assert revoked["nodes"][0]["host_identity_status"] == "revoked"
    with pytest.raises((HostIdentityError, ValueError)):
        pin_from_snapshot(revoked, "gway-004", {"gway-004"}, path)
