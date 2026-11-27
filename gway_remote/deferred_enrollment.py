"""Proof-of-possession preparation ledger for Watchtower, issue #682.

Requires the existing Watchtower SQLite enrollment database.  The operator
entrypoint must authenticate callers; public endpoints may only challenge and
claim.  No execution grant is made by this module.
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

NODE = re.compile(r"gway-[0-9]{3}\Z")
IDENT = re.compile(r"[a-f0-9]{32}\Z")
CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class PreparationRejected(Exception):
    """Safe rejection: never interpolate untrusted fields or secrets."""


def stamp(dt):
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("aware UTC clock required")
    return dt.astimezone(timezone.utc).isoformat()


def proof_message(ident: str, node: str, nonce: str) -> bytes:
    if not IDENT.fullmatch(ident) or not NODE.fullmatch(node) or not CHALLENGE.fullmatch(nonce):
        raise ValueError("invalid signed fields")
    return f"gway-sd-claim-v1\n{ident}\n{node}\n{nonce}\n".encode("ascii")


SCHEMA = """
CREATE TABLE IF NOT EXISTS sd_preparations(
 id TEXT PRIMARY KEY, device TEXT NOT NULL, public_key BLOB NOT NULL,
 created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 claimed_at TEXT, claim_expires_at TEXT, revoked_at TEXT,
 session_id TEXT, sealed_session BLOB,
 state TEXT NOT NULL CHECK(state IN ('prepared','claimed','local_setup_reported','remote_verified'))
);
CREATE UNIQUE INDEX IF NOT EXISTS sd_one_live
 ON sd_preparations(device)
 WHERE revoked_at IS NULL AND state IN ('prepared','claimed','local_setup_reported');
CREATE TABLE IF NOT EXISTS sd_challenges(
 preparation_id TEXT PRIMARY KEY, challenge_hash TEXT NOT NULL,
 expires_at TEXT NOT NULL
);
"""


class DeferredPreparations:
    """One SQLite authority; all lifecycle mutations use BEGIN IMMEDIATE."""

    def __init__(self, path: Path, *, sealing_key: bytes, clock=None):
        self.path = Path(path)
        self._seal = Fernet(sealing_key)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("existing Watchtower enrollment ledger required")
        with self._db() as db:
            db.executescript(SCHEMA)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def _now(self):
        return stamp(self.clock())

    def prepare(self, node: str, key: str, *, hours: int = 24) -> dict:
        """OPERATOR ONLY: issue a per-card preparation, not a bearer URL."""
        if not isinstance(node, str) or not NODE.fullmatch(node):
            raise ValueError("invalid device")
        if type(hours) is not int or not 1 <= hours <= 48:
            raise ValueError("invalid preparation lifetime")
        try:
            raw = base64.urlsafe_b64decode(key + "=")
            if len(raw) != 32 or len(key) != 43:
                raise ValueError()
            Ed25519PublicKey.from_public_bytes(raw)
        except (TypeError, ValueError):
            raise ValueError("invalid Ed25519 public key") from None
        ident = secrets.token_hex(16)
        now = self._now()
        expires = stamp(self.clock() + timedelta(hours=hours))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("UPDATE sd_preparations SET revoked_at=? WHERE "
                           "state='prepared' AND revoked_at IS NULL AND expires_at<=?",
                           (now, now))
                if db.execute("SELECT 1 FROM devices WHERE device=? AND "
                              "state IN ('pending','active')", (node,)).fetchone():
                    raise PreparationRejected("device already registered")
                db.execute("INSERT INTO sd_preparations(id,device,public_key,"
                           "created_at,expires_at,state) VALUES(?,?,?,?,?,'prepared')",
                           (ident, node, raw, now, expires))
                db.execute("COMMIT")
            except sqlite3.IntegrityError:
                db.execute("ROLLBACK")
                raise PreparationRejected("preparation already pending") from None
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return {"id": ident, "device": node, "expires_at": expires, "state": "prepared"}

    def status(self, ident: str) -> dict:
        """OPERATOR ONLY; no key material is returned."""
        if not isinstance(ident, str) or not IDENT.fullmatch(ident):
            raise PreparationRejected("unknown preparation")
        with self._db() as db:
            row = db.execute("SELECT id,device,created_at,expires_at,claimed_at,"
                             "claim_expires_at,revoked_at,state FROM sd_preparations "
                             "WHERE id=?", (ident,)).fetchone()
        if not row:
            raise PreparationRejected("unknown preparation")
        return dict(row)

    def challenge(self, ident: str) -> str:
        if not isinstance(ident, str) or not IDENT.fullmatch(ident):
            raise PreparationRejected("preparation unavailable")
        now = self._now()
        nonce = secrets.token_urlsafe(32)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT * FROM sd_preparations WHERE id=?",
                                 (ident,)).fetchone()
                if (row is None or row["revoked_at"] or not (
                    row["state"] == "prepared" and row["expires_at"] > now or
                    row["state"] == "claimed" and row["claim_expires_at"] > now
                )):
                    raise PreparationRejected("preparation unavailable")
                db.execute("INSERT INTO sd_challenges VALUES(?,?,?) ON CONFLICT("
                           "preparation_id) DO UPDATE SET challenge_hash=excluded."
                           "challenge_hash, expires_at=excluded.expires_at",
                           (ident, hashlib.sha256(nonce.encode()).hexdigest(),
                            stamp(self.clock() + timedelta(minutes=2))))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return nonce

    def claim(self, ident: str, nonce: str, signature: str) -> dict:
        """Issue or re-deliver SAME sealed 2h bootstrap after signed challenge."""
        if (not isinstance(ident, str) or not IDENT.fullmatch(ident) or
                not isinstance(nonce, str) or not CHALLENGE.fullmatch(nonce) or
                not isinstance(signature, str) or len(signature) != 86):
            raise PreparationRejected("invalid claim")
        try:
            sig = base64.urlsafe_b64decode(signature + "==")
            if len(sig) != 64:
                raise ValueError()
        except (ValueError, TypeError):
            raise PreparationRejected("invalid claim") from None
        now = self._now()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT * FROM sd_preparations WHERE id=?", (ident,)).fetchone()
                chal = db.execute("SELECT * FROM sd_challenges WHERE preparation_id=?",
                                  (ident,)).fetchone()
                if (row is None or row["revoked_at"] or not (
                    row["state"] == "prepared" and row["expires_at"] > now or
                    row["state"] == "claimed" and row["claim_expires_at"] > now
                ) or chal is None or chal["expires_at"] <= now or
                    not secrets.compare_digest(chal["challenge_hash"],
                                               hashlib.sha256(nonce.encode()).hexdigest())):
                    raise PreparationRejected("invalid claim")
                try:
                    Ed25519PublicKey.from_public_bytes(row["public_key"]).verify(
                        sig, proof_message(ident, row["device"], nonce))
                except (InvalidSignature, ValueError):
                    raise PreparationRejected("invalid claim") from None
                if row["state"] == "prepared":
                    token = secrets.token_urlsafe(32)
                    invite = secrets.token_urlsafe(32)
                    session_id = secrets.token_hex(16)
                    invite_id = secrets.token_hex(16)
                    until = stamp(self.clock() + timedelta(hours=2))
                    db.execute("UPDATE invitations SET revoked_at=? WHERE device=? "
                               "AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at<=?",
                               (now, row["device"], now))
                    if db.execute("SELECT 1 FROM invitations WHERE device=? AND "
                                  "consumed_at IS NULL AND revoked_at IS NULL",
                                  (row["device"],)).fetchone():
                        raise PreparationRejected("active invitation conflict")
                    db.execute("INSERT INTO invitations(id,device,token_hash,expires_at,"
                               "purpose) VALUES(?,?,?,?,'enroll')",
                               (invite_id, row["device"], hashlib.sha256(invite.encode()).hexdigest(), until))
                    db.execute("INSERT INTO bootstrap_sessions(id,session_hash,invitation_id,"
                               "device,expires_at) VALUES(?,?,?,?,?)",
                               (session_id, hashlib.sha256(token.encode()).hexdigest(),
                                invite_id, row["device"], until))
                    db.execute("UPDATE sd_preparations SET state='claimed',claimed_at=?,"
                               "claim_expires_at=?,session_id=?,sealed_session=? WHERE id=?",
                               (now, until, session_id, self._seal.encrypt(token.encode()), ident))
                else:
                    token = self._seal.decrypt(row["sealed_session"]).decode("ascii")
                    until = row["claim_expires_at"]
                db.execute("DELETE FROM sd_challenges WHERE preparation_id=?", (ident,))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return {"device": row["device"], "state": "claimed",
                "claim_expires_at": until,
                "bootstrap_url": "https://register.gelectriic.com/v1/bootstrap/" + token}

    def revoke(self, ident: str) -> bool:
        """OPERATOR ONLY; revoke active session and invitation atomically."""
        if not isinstance(ident, str) or not IDENT.fullmatch(ident):
            raise PreparationRejected("unknown preparation")
        now = self._now()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT session_id FROM sd_preparations WHERE id=? "
                                 "AND revoked_at IS NULL", (ident,)).fetchone()
                if not row:
                    db.execute("ROLLBACK")
                    return False
                db.execute("UPDATE sd_preparations SET revoked_at=? WHERE id=?", (now, ident))
                db.execute("DELETE FROM sd_challenges WHERE preparation_id=?", (ident,))
                if row["session_id"]:
                    db.execute("UPDATE bootstrap_sessions SET revoked_at=? WHERE id=?",
                               (now, row["session_id"]))
                    db.execute("UPDATE invitations SET revoked_at=? WHERE id=("
                               "SELECT invitation_id FROM bootstrap_sessions WHERE id=?)",
                               (now, row["session_id"]))
                db.execute("COMMIT")
                return True
            except BaseException:
                db.execute("ROLLBACK")
                raise
