"""Rotation must consume fresh approval and preserve audit history."""
import base64
import pytest

from gway_remote.watchtower_enrollment import Ledger, EnrollmentRejected
from gway_remote.host_identity import validate_public_key

KEY = base64.b64encode(bytes(range(32))).decode()
BLOB = bytes((0, 0, 0, 11)) + b"ssh-ed25519" + bytes((0, 0, 0, 32))
OLD = "ssh-ed25519 " + base64.b64encode(BLOB + bytes(range(32))).decode()
NEW = "ssh-ed25519 " + base64.b64encode(BLOB + bytes(range(1, 33))).decode()


def test_approved_host_rotation_is_durable_and_cannot_replay(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3", network="10.90.0.0/24",
                    gateway="10.90.0.1")
    original_token = ledger.invite("gway-004")["token"]
    enrollment = ledger.reserve(device="gway-004", public_key=KEY,
                                token=original_token, occupied=set(), ssh_host_key=OLD)
    ledger.advance(enrollment.operation_id, "committed")
    new_token = ledger.invite("gway-004")["token"]
    with pytest.raises(EnrollmentRejected):
        ledger.rotate_host_identity("gway-004", previous_key=OLD, next_key=NEW,
                                    invitation_token=new_token)
    rotation = ledger.rotate_host_identity("gway-004", previous_key=OLD, next_key=NEW,
                                          invitation_token=new_token, authorized=True)
    assert rotation
    with ledger._connect() as db:
        record = db.execute("SELECT host_public_key FROM host_identities").fetchone()
        audit = db.execute("SELECT previous_host_public_key,next_host_public_key "
                           "FROM host_identity_rotations").fetchone()
        peer = db.execute("SELECT public_key FROM devices WHERE device='gway-004'").fetchone()
    assert record[0] == validate_public_key(NEW)
    assert tuple(audit) == (OLD, NEW)
    assert peer[0] == KEY
    with pytest.raises(EnrollmentRejected):
        ledger.rotate_host_identity("gway-004", previous_key=OLD, next_key=NEW,
                                    invitation_token=new_token, authorized=True)
    assert ledger.revoke_host_identity("gway-004")
    assert not ledger.revoke_host_identity("gway-004")
    with pytest.raises(EnrollmentRejected):
        ledger.rotate_host_identity("gway-004", previous_key=NEW, next_key=OLD,
                                    invitation_token=ledger.invite("gway-004")["token"],
                                    authorized=True)
