"""Host-key enrollment protocol: legacy compatibility and fail-closed validation."""
import base64
import json
import pytest

from gway_remote.wireguard_enrollment_contract import (
    InvalidEnrollment, parse_host_identity_enrollment,
)

WIRE_KEY = base64.b64encode(bytes(range(32))).decode()
HOST_BLOB = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes(range(32))
HOST_KEY = "ssh-ed25519 " + base64.b64encode(HOST_BLOB).decode()
BASE = {"device": "gway-004", "public_key": WIRE_KEY, "token": "x" * 40}


def parse(data):
    return parse_host_identity_enrollment(json.dumps(data).encode())


def test_legacy_still_allowed_but_has_no_attestation():
    assert parse(BASE) == ("gway-004", WIRE_KEY, "x" * 40, None)


def test_host_key_validated_and_bound_to_same_request():
    assert parse(dict(BASE, ssh_host_key=HOST_KEY))[-1] == HOST_KEY


@pytest.mark.parametrize("bad", [
    "ssh-rsa invalid", "ssh-ed25519 not-base64", "ssh-ed25519 " +
    base64.b64encode(b"wrong").decode(), "", None
])
def test_malformed_host_keys_rejected_without_secrets(bad):
    with pytest.raises(InvalidEnrollment, match="invalid enrollment request"):
        parse(dict(BASE, ssh_host_key=bad))


def test_unknown_fields_rejected():
    with pytest.raises(InvalidEnrollment):
        parse(dict(BASE, admin=True))
