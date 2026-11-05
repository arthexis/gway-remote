"""Root-only explicit SSH host attestation for an already enrolled device.

The ED25519 host key MUST be obtained and verified out-of-band by the operator.
Do not infer identity from a reachable SSH or WireGuard endpoint (no TOFU).
"""
from __future__ import annotations

import hashlib
import os
import stat
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .host_identity import validate_public_key
from .inspection_ssh_trust import trusted_file
from .watchtower_enrollment import _now


def host_key_path(node: str) -> Path:
    """Canonical operator-provisioned key file; never discover or trust a host key."""
    from .wireguard_enrollment_contract import DEVICE
    if not isinstance(node, str) or not DEVICE.fullmatch(node):
        raise ValueError("invalid node")
    return Path("/etc/gway-remote") / ("verified-" + node + "-host.pub")


def rotation_token_path(node: str) -> Path:
    """Canonical protected operator-provisioned invitation token for rotation."""
    host_key_path(node)  # Validate node against enrollment contract.
    return Path("/etc/gway-remote") / ("rotation-" + node + ".token")


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


def provision_host_key(node: str, public_key: str, *, dry_run: bool = False) -> Path:
    """Create a protected verified public-key file, never replace another identity.

    The caller is responsible for independent verification of the supplied key.
    """
    from .inspection_ssh_trust import _trusted_parent_directories
    key = validate_public_key(" ".join(public_key.strip().split()[:2]))
    if len(public_key.strip().split()) not in (2, 3):
        raise ValueError("expected one SSH ED25519 public key")
    path = host_key_path(node)
    _trusted_parent_directories(path)
    if path.is_symlink():
        raise ValueError("unsafe SSH host key path")
    if path.exists():
        if verified_host_key(path) != key:
            raise ValueError("host key mismatch; refusing to overwrite")
        return path
    if dry_run:
        return path
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(key + "\n")
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def rotate_verified_host_key(ledger, node: str, public_key: str, *,
                             token_file: Path, dry_run: bool = False) -> dict:
    """Explicit, invitation-authorized rotation using the existing ledger transition.

    The caller must independently verify the new SSH host public key.
    """
    import tempfile
    from .inspection_ssh_trust import trusted_file
    from .watchtower_enrollment import _digest
    key = validate_public_key(" ".join(public_key.strip().split()[:2]))
    if len(public_key.strip().split()) not in (2, 3):
        raise ValueError("expected one SSH ED25519 public key")
    path = host_key_path(node)
    old = verified_host_key(path)
    if old == key:
        raise ValueError("host key unchanged")
    trusted_file(token_file, secret=True)
    token = Path(token_file).read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("rotation authorization token missing")
    now = _now()
    with ledger._connect() as db:
        invitation = db.execute(
            "SELECT id FROM invitations WHERE token_hash=? AND device=? "
            "AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>?",
            (_digest(token), node, now),
        ).fetchone()
        identity = db.execute(
            "SELECT * FROM host_identities WHERE device=? AND state='active'", (node,),
        ).fetchone()
        peer = db.execute(
            "SELECT public_key FROM devices WHERE device=? AND state='active'", (node,),
        ).fetchone()
        duplicate = db.execute(
            "SELECT device FROM host_identities WHERE host_public_key=? AND device!=? AND state='active'",
            (key, node),
        ).fetchone()
        if not invitation or not identity or not peer or duplicate:
            raise ValueError("host rotation preflight rejected")
        if identity["host_public_key"] != old or identity["wireguard_identity"] != peer["public_key"]:
            raise ValueError("host rotation identity mismatch")
    if dry_run:
        return {"node": node, "state": "would_rotate", "identity_verified": True,
                "execute_available": False}
    # Stage the protected replacement first; keep the original until the
    # existing ledger transition has accepted and recorded the rotation.
    fd, temp_name = tempfile.mkstemp(prefix=".verified-host-", dir=str(path.parent))
    staged = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(key + "\n")
            out.flush()
            os.fsync(out.fileno())
        transition = ledger.rotate_host_identity(
            node, previous_key=old, next_key=key,
            invitation_token=token, authorized=True,
        )
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)
    return {"node": node, "state": "rotated", "transition": transition,
            "identity_verified": True, "execute_available": False}
