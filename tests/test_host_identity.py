import base64
from datetime import datetime, timedelta, timezone
import pytest
from gway_remote.host_identity import HostIdentityError, validate_attestation, assert_pinned_identity


def test_attestation_rejects_missing_or_untrusted_identity():
    with pytest.raises(HostIdentityError):
        validate_attestation({"schema": 1, "node": "gway-004"}, node="gway-004")
    with pytest.raises(HostIdentityError):
        assert_pinned_identity(None, {"host_key": "untrusted"})
    with pytest.raises(HostIdentityError):
        assert_pinned_identity("old", {"host_key": "new"})


def test_attestation_validates_key_and_lifecycle():
    now = datetime.now(timezone.utc)
    blob = b"\\x00\\x00\\x00\\x0bssh-ed25519\\x00\\x00\\x00\\x20" + bytes(range(32))
    key = "ssh-ed25519 " + base64.b64encode(blob).decode()
    record = {"schema": 1, "node": "gway-004", "state": "active",
              "rotation_state": "stable", "enrollment_binding": "a" * 64,
              "wireguard_identity": base64.b64encode(bytes(range(32))).decode(),
              "host_public_key": key, "created_at": (now - timedelta(days=1)).isoformat(),
              "valid_until": (now + timedelta(days=1)).isoformat()}
    validated = validate_attestation(record, node="gway-004", now=now)
    assert validated["host_key"] == key
    assert_pinned_identity(key, validated)
    for field, value in [("state", "revoked"), ("rotation_state", "pending"),
                         ("node", "gway-005"), ("host_public_key", "ssh-ed25519 bad")]:
        changed = dict(record, **{field: value})
        with pytest.raises(HostIdentityError):
            validate_attestation(changed, node="gway-004", now=now)
