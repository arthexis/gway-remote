"""Pure central pin composition: no network, root writes or SSH private keys."""
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import pytest

from gway_remote.watchtower_exec_convergence import _entry_and_bytes, ConvergenceRefused

RAW = bytes((0,0,0,11)) + b"ssh-ed25519" + bytes((0,0,0,32)) + bytes(range(32))
SSH = "ssh-ed25519 " + base64.b64encode(RAW).decode()
DIGEST = hashlib.sha256(RAW).hexdigest()
WG = base64.b64encode(bytes(range(32))).decode()
NOW = datetime.now(timezone.utc)
ENTRY = {"node": "gway-001", "address": "10.90.0.2",
         "ssh_host_alias": "gway-001", "known_hosts": "/private/known",
         "identity_file": "/private/key", "host_key_sha256": DIGEST,
         "remote_user": "gway-relay"}


def before():
    c = json.dumps({"enabled": True, "nodes": [dict(ENTRY)]}).encode()
    k = ("gway-001 " + SSH + "\n").encode()
    host = {"schema":1,"node":"gway-005","wireguard_identity":WG,
            "host_public_key":SSH,"enrollment_binding":"a"*64,
            "state":"active","rotation_state":"stable",
            "created_at":(NOW-timedelta(minutes=2)).isoformat(),
            "valid_until":(NOW+timedelta(days=7)).isoformat()}
    s = {"schema":2,"nodes":[{"node":"gway-005","state":"active",
                                "address":"10.90.0.5/32",
                                "host_identity":host}]}
    return c,k,s


def test_grant_is_pinned_by_existing_attested_identity_only():
    config, known, snapshot = before()
    future, known2 = _entry_and_bytes("gway-005", True, config, known, snapshot)
    j = json.loads(future)
    assert len(j["nodes"]) == 2
    assert j["nodes"][0] == ENTRY
    assert j["nodes"][-1]["host_key_sha256"] == DIGEST
    assert j["nodes"][-1]["remote_user"] == "gway-relay"
    assert known2.endswith(("gway-005 " + SSH + "\n").encode())
    assert _entry_and_bytes("gway-005", False, future, known2, snapshot)[0] == (
        json.dumps({"enabled":True,"nodes":[ENTRY]},
                   separators=(",",":"),sort_keys=True) + "\n").encode()


def test_pin_is_idempotent_and_stale_or_changed_key_is_refused():
    config, known, snapshot = before()
    next_config, next_known = _entry_and_bytes("gway-005", True, config, known, snapshot)
    assert _entry_and_bytes("gway-005", True, next_config, next_known, snapshot) == (
        next_config, next_known)
    snapshot["nodes"][0]["host_identity"]["host_public_key"] = "ssh-ed25519 " + base64.b64encode(
        RAW[:-1] + b"Z").decode()
    with pytest.raises(ConvergenceRefused):
        _entry_and_bytes("gway-005", True, next_config, next_known, snapshot)


def test_unattested_or_removed_node_is_denied():
    config, known, snapshot = before()
    snapshot["nodes"][0]["host_identity"]["state"] = "revoked"
    with pytest.raises(ValueError):
        _entry_and_bytes("gway-005", True, config, known, snapshot)
    snapshot["nodes"][0]["state"] = "revoked"
    assert _entry_and_bytes("gway-005", False, config, known, snapshot) == (
        config, known)


def test_unknown_preexisting_pin_is_not_replaced():
    config, known, snapshot = before()
    known += ("gway-005 ssh-ed25519 " + base64.b64encode(RAW[:-1]+b"Z").decode() + "\n").encode()
    with pytest.raises(ConvergenceRefused):
        _entry_and_bytes("gway-005", True, config, known, snapshot)


def test_named_standalone_satellite_cannot_gain_restricted_execution():
    config, known, snapshot = before()
    with pytest.raises(ConvergenceRefused):
        _entry_and_bytes("ocpp-abb-1", True, config, known, snapshot)


def test_revoke_only_other_transport_is_denied():
    config, known, snapshot = before()
    snapshot["nodes"][0]["node"] = "gway-001"
    with pytest.raises(ConvergenceRefused):
        _entry_and_bytes("gway-001", False, config, known, snapshot)

def test_revoke_works_for_inactive_previously_enrolled_node():
    config, known, snapshot = before()
    configured, pinned = _entry_and_bytes("gway-005", True, config, known, snapshot)
    snapshot["nodes"][0]["state"] = "revoked"
    reduced, pin_after = _entry_and_bytes("gway-005", False, configured, pinned, snapshot)
    assert len(json.loads(reduced)["nodes"]) == 1
    assert pin_after == pinned
