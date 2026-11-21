"""Durable Watchtower enrollment registry and SQLite transactions.

This module owns schema compatibility, invitation/session semantics, host
attestations, addresses and operation states. Importing it has no side effects.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from ipaddress import IPv4Address, IPv4Network, ip_network
from pathlib import Path
from typing import Iterable

from .wireguard_enrollment_contract import DEVICE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class EnrollmentRejected(Exception):
    """Public-safe rejection.  Messages must not interpolate request fields."""


class EnrollmentFailure(Exception):
    """Operator-visible local failure; never returned to the HTTP client."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY,
    device TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    revoked_at TEXT,
    purpose TEXT NOT NULL DEFAULT 'enroll' CHECK(purpose IN ('enroll','host_identity_repair')),
    replace_authorized INTEGER NOT NULL DEFAULT 0 CHECK(replace_authorized IN (0,1))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_invitation
    ON invitations(device) WHERE consumed_at IS NULL AND revoked_at IS NULL;
CREATE TABLE IF NOT EXISTS bootstrap_sessions (
    id TEXT PRIMARY KEY,
    session_hash TEXT NOT NULL UNIQUE,
    invitation_id TEXT NOT NULL REFERENCES invitations(id),
    device TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS devices (
    device TEXT PRIMARY KEY,
    public_key TEXT NOT NULL UNIQUE,
    address TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK(state IN ('pending','active','revoked')),
    operation_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS host_identities (
    device TEXT PRIMARY KEY REFERENCES devices(device),
    operation_id TEXT NOT NULL UNIQUE,
    wireguard_identity TEXT NOT NULL,
    host_public_key TEXT NOT NULL,
    enrollment_binding TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','active','revoked')),
    created_at TEXT NOT NULL,
    valid_until TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS host_identity_rotations (
    id TEXT PRIMARY KEY,
    device TEXT NOT NULL,
    wireguard_identity TEXT NOT NULL,
    previous_host_public_key TEXT NOT NULL,
    next_host_public_key TEXT NOT NULL,
    authorization_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('committed','revoked'))
);
CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY,
    device TEXT NOT NULL,
    public_key TEXT NOT NULL,
    address TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('reserved','config_written','runtime_applied','committed','rolled_back','failed')),
    backup_path TEXT,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Enrollment:
    operation_id: str
    device: str
    public_key: str
    address: str
    already_active: bool = False


class Ledger:
    """Durable registry. Tokens are hashes; request tokens are never persisted."""

    def __init__(self, path: Path, *, network: str, gateway: str, read_only: bool = False):
        self.path = Path(path)
        self.read_only = read_only
        self.network = ip_network(network, strict=True)
        if not isinstance(self.network, IPv4Network):
            raise ValueError("Watchtower network must be IPv4")
        self.gateway = IPv4Address(gateway)
        if self.gateway not in self.network:
            raise ValueError("gateway must be inside Watchtower network")
        if self.read_only:
            if self.path.is_symlink() or not self.path.is_file():
                raise ValueError("unsafe or missing enrollment ledger")
            return
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("unsafe enrollment ledger")
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(invitations)")}
            if "purpose" not in columns:
                connection.execute(
                    "ALTER TABLE invitations ADD COLUMN purpose TEXT NOT NULL DEFAULT 'enroll'"
                )
            if "replace_authorized" not in columns:
                connection.execute("ALTER TABLE invitations ADD COLUMN replace_authorized INTEGER NOT NULL DEFAULT 0")
        self.path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro",
                                         uri=True, timeout=30, isolation_level=None)
            connection.execute("PRAGMA query_only=ON")
        else:
            connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _transaction(self):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    def invite(self, device: str, *, minutes: int = 15,
               purpose: str = "enroll", replace: bool = False, supersede_pending: bool = False) -> dict:
        if not isinstance(device, str) or not DEVICE.fullmatch(device):
            raise ValueError("invalid Watchtower device")
        if not 1 <= minutes <= 60:
            raise ValueError("invitation lifetime must be between 1 and 60 minutes")
        if purpose not in {"enroll", "host_identity_repair"}:
            raise ValueError("invalid Watchtower invitation purpose")
        token = secrets.token_urlsafe(32)
        ident = secrets.token_hex(16)
        expires = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        with self._transaction() as connection:
            if supersede_pending:
                # Reissuing a bootstrap URL invalidates the previous unused URL and
                # invitation atomically; an enrolled device is never modified.
                connection.execute(
                    "UPDATE bootstrap_sessions SET revoked_at=? WHERE device=? "
                    "AND consumed_at IS NULL AND revoked_at IS NULL", (_now(), device))
                connection.execute(
                    "UPDATE invitations SET revoked_at=? WHERE device=? "
                    "AND consumed_at IS NULL AND revoked_at IS NULL", (_now(), device))
            connection.execute("UPDATE invitations SET revoked_at=? WHERE device=? AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at<=?", (_now(), device, _now()))
            connection.execute(
                "INSERT INTO invitations(id,device,token_hash,expires_at,purpose,replace_authorized) VALUES(?,?,?,?,?,?)",
                (ident, device, _digest(token), expires, purpose, int(replace)),
            )
        return {"id": ident, "device": device, "token": token, "expires_at": expires}

    def register(self, device: str, *, minutes: int = 15, public_url: str,
                 repair_host_identity: bool = False, replace: bool = False) -> dict:
        """Create one short-lived URL bearer; underlying invitation token stays private."""
        from urllib.parse import urlsplit

        origin = urlsplit(public_url)
        if (origin.scheme != "https" or origin.hostname != "register.gelectriic.com"
                or origin.username or origin.password or origin.query or origin.fragment
                or origin.path not in ("", "/") or origin.port not in (None, 443)):
            raise ValueError("invalid approved registration origin")
        if repair_host_identity and replace:
            raise ValueError("replacement and host identity repair are mutually exclusive")
        invitation = self.invite(
            device, minutes=minutes,
            purpose="host_identity_repair" if repair_host_identity else "enroll", replace=replace,
            supersede_pending=True,
        )
        secret = secrets.token_urlsafe(32)
        session_id = secrets.token_hex(16)
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO bootstrap_sessions(id,session_hash,invitation_id,device,expires_at) VALUES(?,?,?,?,?)",
                (session_id, _digest(secret), invitation["id"], device, invitation["expires_at"]),
            )
        return {"id": session_id, "device": device,
                "repair_host_identity": repair_host_identity,
                "replace": replace,
                "url": f"https://register.gelectriic.com/v1/bootstrap/{secret}" + ("?replace=true" if replace else ""),
                "expires_at": invitation["expires_at"]}

    def bootstrap_session(self, secret: str) -> dict:
        """Inspect a URL bearer without exposing an invitation or changing state."""
        if not isinstance(secret, str) or len(secret) > 128 or len(secret) < 32:
            raise EnrollmentRejected("bootstrap rejected")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT s.*, i.revoked_at AS invitation_revoked, i.consumed_at AS invitation_consumed, i.purpose, i.replace_authorized "
                "FROM bootstrap_sessions s JOIN invitations i ON i.id=s.invitation_id "
                "WHERE s.session_hash=?", (_digest(secret),),
            ).fetchone()
        if (row is None or row["revoked_at"] or row["consumed_at"] or
                row["invitation_revoked"] or
                row["expires_at"] <= _now()):
            raise EnrollmentRejected("bootstrap rejected")
        return {"id": row["id"], "device": row["device"], "expires_at": row["expires_at"],
                "repair_host_identity": row["purpose"] == "host_identity_repair",
                "replace": bool(row["replace_authorized"])}

    def complete_bootstrap(self, secret: str, device: str, public_key: str) -> bool:
        """Consume URL after client confirms local installation and startup."""
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM bootstrap_sessions WHERE session_hash=?", (_digest(secret),),
            ).fetchone()
            if row is None or row["device"] != device or row["revoked_at"]:
                raise EnrollmentRejected("bootstrap rejected")
            peer = connection.execute(
                "SELECT 1 FROM devices WHERE device=? AND public_key=? AND state='active'",
                (device, public_key),
            ).fetchone()
            if peer is None:
                raise EnrollmentRejected("bootstrap rejected")
            if row["consumed_at"]:
                return False
            connection.execute(
                "UPDATE bootstrap_sessions SET consumed_at=? WHERE id=?", (_now(), row["id"]),
            )
            return True

    def revoke_bootstrap(self, session_id: str) -> bool:
        """Revoke bootstrap and matching unused invitation together."""
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT invitation_id FROM bootstrap_sessions WHERE id=? AND revoked_at IS NULL "
                "AND consumed_at IS NULL", (session_id,),
            ).fetchone()
            if row is None:
                return False
            now = _now()
            connection.execute("UPDATE bootstrap_sessions SET revoked_at=? WHERE id=?", (now, session_id))
            connection.execute("UPDATE invitations SET revoked_at=? WHERE id=? AND consumed_at IS NULL",
                               (now, row["invitation_id"]))
        return True

    def bootstrap_status(self) -> list[dict]:
        """Metadata only: no invitation tokens, bearer values, or their hashes."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,device,expires_at,consumed_at,revoked_at FROM bootstrap_sessions "
                "ORDER BY expires_at DESC LIMIT 100"
            )
            return [dict(row) for row in rows]

    def revoke(self, invitation_id: str) -> bool:
        with self._transaction() as connection:
            result = connection.execute("UPDATE invitations SET revoked_at=? WHERE id=? AND consumed_at IS NULL AND revoked_at IS NULL", (_now(), invitation_id))
        return result.rowcount == 1

    def _allocate(self, connection: sqlite3.Connection, occupied: Iterable[str]) -> str:
        reserved = {self.gateway}
        for value in occupied:
            try:
                item = ip_network(value, strict=False)
            except ValueError:
                continue
            if item.version == 4:
                reserved.update(item.hosts() if item.prefixlen < 32 else [item.network_address])
        reserved.update(IPv4Address(row[0].split("/", 1)[0]) for row in connection.execute("SELECT address FROM devices WHERE state != 'revoked'"))
        for candidate in self.network.hosts():
            if candidate not in reserved:
                return f"{candidate}/32"
        raise EnrollmentFailure("Watchtower address pool is exhausted")

    def reserve(self, *, device: str, public_key: str, token: str, occupied: Iterable[str], backup_directory: Path | None = None, ssh_host_key: str | None = None) -> Enrollment:
        from .host_identity import validate_public_key
        if ssh_host_key is not None:
            ssh_host_key = validate_public_key(ssh_host_key)
        now = _now()
        token_hash = _digest(token)
        with self._transaction() as connection:
            invitation = connection.execute("SELECT * FROM invitations WHERE token_hash=?", (token_hash,)).fetchone()
            if invitation is None:
                session = connection.execute(
                    "SELECT * FROM bootstrap_sessions WHERE session_hash=?", (token_hash,),
                ).fetchone()
                if (session is None or session["device"] != device or session["revoked_at"]
                        or session["consumed_at"] or session["expires_at"] <= now):
                    raise EnrollmentRejected("enrollment rejected")
                invitation = connection.execute(
                    "SELECT * FROM invitations WHERE id=?", (session["invitation_id"],),
                ).fetchone()
                token_hash = invitation["token_hash"]
            if invitation is None or invitation["revoked_at"]:
                raise EnrollmentRejected("enrollment rejected")
            if invitation["device"] != device:
                raise EnrollmentRejected("enrollment rejected")
            if invitation["purpose"] != "enroll":
                raise EnrollmentRejected("enrollment rejected")
            existing = connection.execute("SELECT * FROM devices WHERE device=?", (device,)).fetchone()
            if existing is not None:
                if existing["public_key"] != public_key or existing["state"] == "revoked":
                    raise EnrollmentRejected("enrollment rejected")
                identity = connection.execute("SELECT host_public_key FROM host_identities WHERE device=?", (device,)).fetchone()
                if ssh_host_key is not None and (identity is None or identity["host_public_key"] != ssh_host_key):
                    raise EnrollmentRejected("enrollment rejected")
                operation = connection.execute("SELECT * FROM operations WHERE id=?", (existing["operation_id"],)).fetchone()
                if operation and operation["state"] == "committed":
                    return Enrollment(operation["id"], device, public_key, existing["address"], True)
                return Enrollment(existing["operation_id"], device, public_key, existing["address"])
            if invitation["consumed_at"] or invitation["expires_at"] <= now:
                raise EnrollmentRejected("enrollment rejected")
            duplicate = connection.execute("SELECT 1 FROM devices WHERE public_key=?", (public_key,)).fetchone()
            if duplicate:
                raise EnrollmentRejected("enrollment rejected")
            address = self._allocate(connection, occupied)
            operation_id = secrets.token_hex(16)
            backup_path = str(Path(backup_directory) / f"{operation_id}.conf") if backup_directory else None
            connection.execute("INSERT INTO devices(device,public_key,address,state,operation_id) VALUES(?,?,?,?,?)", (device, public_key, address, "pending", operation_id))
            connection.execute("INSERT INTO operations(id,device,public_key,address,token_hash,state,backup_path,created_at,updated_at) VALUES(?,?,?,?,?,'reserved',?,?,?)", (operation_id, device, public_key, address, token_hash, backup_path, now, now))
            if ssh_host_key is not None:
                connection.execute(
                    "INSERT INTO host_identities(device,operation_id,wireguard_identity,host_public_key,enrollment_binding,state,created_at,valid_until) VALUES(?,?,?,?,?,'pending',?,?)",
                    (device, operation_id, public_key, ssh_host_key,
                     hashlib.sha256(invitation["id"].encode("ascii")).hexdigest(), now,
                     (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()))
        return Enrollment(operation_id, device, public_key, address)

    def repair_host_identity(self, *, device: str, public_key: str, token: str,
                             ssh_host_key: str) -> Enrollment:
        """Attach the first attestation to an unchanged active tunnel.

        This is intentionally narrower than enrollment: a purpose-bound,
        one-time repair invitation may only bind the active device's existing
        WireGuard identity to its current ED25519 host public key.  It never
        allocates an address or invokes WireGuard.
        """
        from .host_identity import validate_public_key

        host_key = validate_public_key(ssh_host_key)
        now = _now()
        token_hash = _digest(token)
        with self._transaction() as connection:
            invitation = connection.execute(
                "SELECT * FROM invitations WHERE token_hash=?", (token_hash,)
            ).fetchone()
            if invitation is None:
                session = connection.execute(
                    "SELECT * FROM bootstrap_sessions WHERE session_hash=?", (token_hash,)
                ).fetchone()
                if (session is None or session["device"] != device or session["revoked_at"]
                        or session["consumed_at"] or session["expires_at"] <= now):
                    raise EnrollmentRejected("host identity repair rejected")
                invitation = connection.execute(
                    "SELECT * FROM invitations WHERE id=?", (session["invitation_id"],)
                ).fetchone()
                token_hash = invitation["token_hash"] if invitation else token_hash
            if (invitation is None or invitation["device"] != device or invitation["revoked_at"]
                    or invitation["purpose"] != "host_identity_repair"):
                raise EnrollmentRejected("host identity repair rejected")
            peer = connection.execute(
                "SELECT * FROM devices WHERE device=? AND state='active'", (device,)
            ).fetchone()
            if peer is None or peer["public_key"] != public_key:
                raise EnrollmentRejected("host identity repair rejected")
            identity = connection.execute(
                "SELECT * FROM host_identities WHERE device=?", (device,)
            ).fetchone()
            if identity is not None:
                if (identity["state"] != "active"
                        or identity["wireguard_identity"] != public_key
                        or identity["host_public_key"] != host_key):
                    raise EnrollmentRejected("host identity repair rejected")
                return Enrollment(peer["operation_id"], device, public_key, peer["address"], True)
            if invitation["consumed_at"] or invitation["expires_at"] <= now:
                raise EnrollmentRejected("host identity repair rejected")
            operation_id = secrets.token_hex(16)
            binding = hashlib.sha256(invitation["id"].encode("ascii")).hexdigest()
            connection.execute(
                "INSERT INTO operations(id,device,public_key,address,token_hash,state,detail,created_at,updated_at) "
                "VALUES(?,?,?,?,?,'committed','host_identity_repair',?,?)",
                (operation_id, device, public_key, peer["address"], token_hash, now, now),
            )
            connection.execute(
                "INSERT INTO host_identities(device,operation_id,wireguard_identity,host_public_key,enrollment_binding,state,created_at,valid_until) "
                "VALUES(?,?,?,?,?,'active',?,?)",
                (device, operation_id, public_key, host_key, binding, now,
                 (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()),
            )
            connection.execute("UPDATE invitations SET consumed_at=? WHERE id=?", (now, invitation["id"]))
        return Enrollment(operation_id, device, public_key, peer["address"], True)

    def advance(self, operation_id: str, state: str, *, backup_path: str | None = None, detail: str = "") -> None:
        allowed = {"config_written", "runtime_applied", "committed", "rolled_back", "failed"}
        if state not in allowed:
            raise ValueError("invalid operation state")
        with self._transaction() as connection:
            result = connection.execute("UPDATE operations SET state=?, backup_path=COALESCE(?, backup_path), detail=?, updated_at=? WHERE id=?", (state, backup_path, detail, _now(), operation_id))
            if result.rowcount != 1:
                raise EnrollmentFailure("unknown Watchtower operation")
            if state == "committed":
                operation = connection.execute("SELECT token_hash FROM operations WHERE id=?", (operation_id,)).fetchone()
                connection.execute("UPDATE devices SET state='active' WHERE operation_id=?", (operation_id,))
                connection.execute("UPDATE host_identities SET state='active' WHERE operation_id=?", (operation_id,))
                connection.execute("UPDATE invitations SET consumed_at=? WHERE token_hash=?", (_now(), operation["token_hash"]))
            elif state in {"rolled_back", "failed"}:
                connection.execute("DELETE FROM host_identities WHERE operation_id=? AND state='pending'", (operation_id,))
                connection.execute("DELETE FROM devices WHERE operation_id=? AND state='pending'", (operation_id,))

    def revoke_host_identity(self, device: str) -> bool:
        """Irreversibly block host attestation without revoking the WireGuard peer.

        Called only through the private Watchtower administrative surface.
        Re-enrollment must not silently restore an identity after revocation.
        """
        if not isinstance(device, str) or not DEVICE.fullmatch(device):
            raise ValueError("invalid device")
        with self._transaction() as db:
            result = db.execute(
                "UPDATE host_identities SET state='revoked' "
                "WHERE device=? AND state='active'", (device,))
        return result.rowcount == 1

    def rotate_host_identity(self, device: str, *, previous_key: str,
                             next_key: str, invitation_token: str,
                             authorized: bool = False) -> str:
        """Private, explicit rotation tied to a newly issued unused invitation.

        No public HTTP route calls this method. WireGuard identity is unchanged.
        The previous key and authorization are retained in an immutable history.
        """
        from .host_identity import validate_public_key
        if not authorized:
            raise EnrollmentRejected("host rotation not authorized")
        if not isinstance(device, str) or not DEVICE.fullmatch(device):
            raise EnrollmentRejected("invalid device")
        old = validate_public_key(previous_key)
        new = validate_public_key(next_key)
        if old == new:
            raise EnrollmentRejected("host key unchanged")
        now = _now()
        with self._transaction() as db:
            invitation = db.execute(
                "SELECT id FROM invitations WHERE token_hash=? AND device=? "
                "AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>?",
                (_digest(invitation_token), device, now),
            ).fetchone()
            identity = db.execute(
                "SELECT * FROM host_identities WHERE device=? AND state='active'",
                (device,),
            ).fetchone()
            peer = db.execute(
                "SELECT public_key FROM devices WHERE device=? AND state='active'",
                (device,),
            ).fetchone()
            if not invitation or not identity or not peer:
                raise EnrollmentRejected("host rotation rejected")
            if peer["public_key"] != identity["wireguard_identity"] or identity["host_public_key"] != old:
                raise EnrollmentRejected("host rotation identity mismatch")
            authorization_id = invitation["id"]
            rotation_id = secrets.token_hex(16)
            db.execute(
                "INSERT INTO host_identity_rotations "
                "(id,device,wireguard_identity,previous_host_public_key,next_host_public_key,"
                "authorization_id,created_at,state) VALUES (?,?,?,?,?,?,?,'committed')",
                (rotation_id, device, peer["public_key"], old, new, authorization_id, now),
            )
            updated = db.execute(
                "UPDATE host_identities SET host_public_key=?, enrollment_binding=?,"
                "created_at=?,valid_until=? WHERE device=? AND state='active' AND host_public_key=?",
                (new, hashlib.sha256(authorization_id.encode("ascii")).hexdigest(),
                 now, (datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
                 device, old),
            )
            if updated.rowcount != 1:
                raise EnrollmentRejected("host rotation rejected")
            db.execute("UPDATE invitations SET consumed_at=? WHERE id=?", (now, authorization_id))
        return rotation_id

    def pending(self) -> list[dict]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM operations WHERE state NOT IN ('committed','rolled_back') ORDER BY created_at")]

    def inspection_snapshot(self) -> dict:
        """Read-only private export; never exposed by the public HTTP handler."""
        from .node_inspection import registry_snapshot
        return registry_snapshot(self)

    def status(self) -> dict:
        with self._connect() as connection:
            return {"invitations": connection.execute("SELECT count(*) FROM invitations WHERE consumed_at IS NULL AND revoked_at IS NULL").fetchone()[0], "devices": connection.execute("SELECT count(*) FROM devices WHERE state='active'").fetchone()[0], "pending_operations": connection.execute("SELECT count(*) FROM operations WHERE state NOT IN ('committed','rolled_back')").fetchone()[0]}


