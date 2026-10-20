"""Watchtower invitation state. Offline only; no HTTP routes or hub changes."""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

NODE = re.compile(r"^gway-[0-9]{3,}$")
SCHEMA = """
CREATE TABLE IF NOT EXISTS invitations (
 id TEXT PRIMARY KEY,
 node TEXT NOT NULL,
 secret_hash TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 consumed_at TEXT,
 revoked_at TEXT,
 CHECK (consumed_at IS NULL OR revoked_at IS NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS pending_node_invitation
 ON invitations(node) WHERE consumed_at IS NULL AND revoked_at IS NULL;
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


class InvitationStore:
    """Transactional one-use grants; secrets returned only at creation."""

    def __init__(self, database: Path):
        self.database = Path(database)
        self.database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database, timeout=30, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.database.chmod(0o600)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.connection.close()

    def invite(self, node: str, *, minutes: int = 15, now: datetime | None = None) -> dict:
        if not NODE.fullmatch(node):
            raise ValueError("invalid node identity")
        if type(minutes) is not int or not 1 <= minutes <= 60:
            raise ValueError("invitation lifetime must be between 1 and 60 minutes")
        now = now or utcnow()
        secret = secrets.token_urlsafe(32)
        identity = secrets.token_hex(16)
        expires = now + timedelta(minutes=minutes)
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                self.connection.execute(
                    "UPDATE invitations SET revoked_at=? WHERE node=? AND consumed_at IS NULL "
                    "AND revoked_at IS NULL AND expires_at<=?",
                    (now.isoformat(), node, now.isoformat()))
                self.connection.execute(
                    "INSERT INTO invitations (id,node,secret_hash,created_at,expires_at) VALUES (?,?,?,?,?)",
                    (identity, node, _hash(secret), now.isoformat(), expires.isoformat()))
                self.connection.execute("COMMIT")
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise
        return {"id": identity, "node": node, "token": secret,
                "expires_at": expires.isoformat()}

    def redeem(self, identity: str, secret: str, *, now: datetime | None = None) -> str | None:
        """Atomically consume a grant. Does not provision any WireGuard peer."""
        now = (now or utcnow()).isoformat()
        if not isinstance(secret, str) or not isinstance(identity, str):
            return None
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                row = self.connection.execute(
                    "SELECT node FROM invitations WHERE id=? AND secret_hash=? "
                    "AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>?",
                    (identity, _hash(secret), now)).fetchone()
                if row:
                    self.connection.execute(
                        "UPDATE invitations SET consumed_at=? WHERE id=?", (now, identity))
                self.connection.execute("COMMIT")
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise
        return row["node"] if row else None

    def revoke(self, identity: str, *, now: datetime | None = None) -> bool:
        with self.connection:
            result = self.connection.execute(
                "UPDATE invitations SET revoked_at=? WHERE id=? AND consumed_at IS NULL "
                "AND revoked_at IS NULL",
                ((now or utcnow()).isoformat(), identity))
        return result.rowcount == 1

    def list_metadata(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute(
            "SELECT id,node,created_at,expires_at,consumed_at,revoked_at "
            "FROM invitations ORDER BY created_at DESC")]
