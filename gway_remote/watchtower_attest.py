"""Root-only explicit SSH host attestation for an already enrolled device.

The ED25519 host key MUST be obtained and verified out-of-band by the operator.
Do not infer identity from a reachable SSH or WireGuard endpoint (no TOFU).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .host_identity import validate_public_key
from .inspection_ssh_trust import trusted_file
from .watchtower_enrollment import _now


def verified_host_key(path: Path) -> str:
    trusted_file(path)
    lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
    if len(lines) != 1:
        raise ValueError("SSH host key file must contain exactly one public key")
    fields = lines[0].split()
    if len(fields) < 2 or fields[0] != "ssh-ed25519":
        raise ValueError("SSH host key must be ED25519")
    # OpenSSH host *.pub files ordinarily have a trailing hostname comment.
    # Never interpret that comment as an authenticated identity.
    return validate_public_key(" ".join(fields[:2]))


def attest_in_transaction(db, node: str, host_key: str, *, dry_run: bool = False) -> str:
    """Bind unchanged active WireGuard identity to independently verified SSH key."""
    from .wireguard_enrollment_contract import DEVICE
    if not isinstance(node, str) or not DEVICE.fullmatch(node):
        raise ValueError("invalid node")
    host_key = validate_public_key(host_key)
    peer = db.execute("SELECT * FROM devices WHERE device=? AND state='active'", (node,)).fetchone()
    if peer is None:
        raise ValueError("node is not actively enrolled")
    duplicate = db.execute(
        "SELECT device FROM host_identities WHERE host_public_key=? AND device!=? AND state='active'",
        (host_key, node),
    ).fetchone()
    if duplicate is not None:
        raise ValueError("SSH host public key is already attested to another node")
    existing = db.execute("SELECT * FROM host_identities WHERE device=?", (node,)).fetchone()
    if existing is not None:
        if existing["state"] != "active":
            raise ValueError("revoked or pending host identity cannot be reattested")
        if existing["wireguard_identity"] != peer["public_key"] or existing["host_public_key"] != host_key:
            raise ValueError("host identity mismatch; use the explicit rotation procedure")
        if datetime.fromisoformat(existing["valid_until"]) <= datetime.now(timezone.utc):
            raise ValueError("expired identity requires a new authorized transition")
        return "already_attested"
    if dry_run:
        return "would_attest"
    now = _now()
    operation_id = secrets.token_hex(16)
    binding = hashlib.sha256(("attest:" + operation_id + ":" + peer["public_key"]).encode("ascii")).hexdigest()
    db.execute(
        "INSERT INTO operations(id,device,public_key,address,token_hash,state,detail,created_at,updated_at) "
        "VALUES(?,?,?,?,?,'committed','host_identity_attest',?,?)",
        (operation_id, node, peer["public_key"], peer["address"],
         hashlib.sha256(("attest-token:" + operation_id).encode("ascii")).hexdigest(), now, now),
    )
    db.execute(
        "INSERT INTO host_identities(device,operation_id,wireguard_identity,host_public_key,enrollment_binding,"
        "state,created_at,valid_until) VALUES(?,?,?,?,?,'active',?,?)",
        (node, operation_id, peer["public_key"], host_key, binding, now,
         (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()),
    )
    return "attested"


def attest(ledger, *, node: str, host_key_file: Path, dry_run: bool = False) -> dict:
    host_key = verified_host_key(host_key_file)
    with (ledger._connect() if dry_run else ledger._transaction()) as db:
        state = attest_in_transaction(db, node, host_key, dry_run=dry_run)
    return {"node": node, "state": state,
            "identity_verified": state in ("attested", "already_attested"),
            "execute_available": False}
