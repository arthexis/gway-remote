"""Watchtower-only WebAuthn persistence primitives (B1, NOT an authenticator).

There are deliberately no HTTP routes, bearer issuance hooks, assertion
verification, or Android calls. Later increments must verify attestation and
assertion cryptographically BEFORE using the internal credential store.
"""
import hashlib
from contextlib import closing
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

CHALLENGE_TTL = 120
ENROLLMENT_GRANT_TTL = 600
ALLOWED_ACTIONS = frozenset({
    "passkey.enroll", "bearer.issue", "secret.reveal", "secret.update",
})
_ALLOWED_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_ALLOWED_ORIGIN = "https://remote.arthexis.com"
_RP_ID = "remote.arthexis.com"


def _check_identifier(value):
    if not isinstance(value, str) or not _ALLOWED_ID.fullmatch(value):
        raise ValueError("invalid_identifier")
    return value


class WebAuthnLedger:
    """Private Watchtower schema; possession of this object grants NO authority."""

    def __init__(self, database, *, now=None):
        self.path = Path(database)
        self.now = now or time.time

    def _connect(self):
        if self.path.is_symlink():
            raise ValueError("unsafe_database")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.exists():
            mode = self.path.stat().st_mode
            if not self.path.is_file() or mode & 0o077:
                raise ValueError("unsafe_database_permissions")
        db = sqlite3.connect(str(self.path), timeout=5)
        try:
            os.chmod(self.path, 0o600)
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("""CREATE TABLE IF NOT EXISTS credentials (
                credential_id TEXT PRIMARY KEY,
                principal TEXT NOT NULL,
                public_key BLOB NOT NULL,
                sign_count INTEGER NOT NULL DEFAULT 0,
                added_at INTEGER NOT NULL,
                revoked_at INTEGER
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS challenges (
                challenge_hash BLOB PRIMARY KEY,
                principal TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS challenges_expiry ON challenges(expires_at)")
            db.execute("""CREATE TABLE IF NOT EXISTS enrollment_grants (
                grant_hash BLOB PRIMARY KEY, principal TEXT NOT NULL,
                expires_at INTEGER NOT NULL, used_at INTEGER)""")
            db.execute("""CREATE TABLE IF NOT EXISTS enrollment_tickets (
                ticket_hash BLOB PRIMARY KEY, challenge_hash BLOB NOT NULL,
                principal TEXT NOT NULL, expires_at INTEGER NOT NULL,
                used_at INTEGER)""")
            db.commit()
        except Exception:
            db.close()
            raise
        return db

    def begin(self, *, principal, action, target):
        """Create an action-bound, single-use challenge (never a permission).

        The caller must independently authenticate the principal and establish
        entitlement to this action before invoking begin. The WebAuthn verifier
        must check RP ID, HTTPS origin, type, challenge, signature, and UV.
        """
        principal = _check_identifier(principal)
        target = _check_identifier(target)
        if action not in ALLOWED_ACTIONS:
            raise ValueError("invalid_action")
        raw = secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw.encode("ascii")).digest()
        now = int(self.now())
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM challenges WHERE expires_at < ?", (now - 3600,))
            db.execute("INSERT INTO challenges VALUES (?, ?, ?, ?, ?, NULL)",
                       (digest, principal, action, target, now + CHALLENGE_TTL))
        return {"challenge": raw, "rp_id": _RP_ID, "origin": _ALLOWED_ORIGIN,
                "expires_at": now + CHALLENGE_TTL}

    def consume(self, *, challenge, principal, action, target):
        """Burn a challenge regardless of verification outcome.

        Returns only whether the one-use, unexpired intent matched. This is
        NOT a WebAuthn signature or authorization check. The cryptographic
        verifier in B2/C must run separately before any privileged operation.
        """
        principal = _check_identifier(principal)
        target = _check_identifier(target)
        if action not in ALLOWED_ACTIONS or not isinstance(challenge, str) or len(challenge) > 128:
            return False
        digest = hashlib.sha256(challenge.encode("utf-8")).digest()
        now = int(self.now())
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT principal,action,target,expires_at,consumed_at FROM challenges WHERE challenge_hash=?",
                (digest,)).fetchone()
            if row is None:
                return False
            db.execute("UPDATE challenges SET consumed_at=? WHERE challenge_hash=? AND consumed_at IS NULL",
                       (now, digest))
            return bool(row[0] == principal and row[1] == action and row[2] == target
                        and row[3] > now and row[4] is None)

    def create_enrollment_grant(self, *, principal):
        """Operator-only primitive. NEVER expose this method via HTTP."""
        principal = _check_identifier(principal)
        grant = secrets.token_urlsafe(32)
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO enrollment_grants VALUES (?, ?, ?, NULL)",
                       (hashlib.sha256(grant.encode("ascii")).digest(), principal,
                        int(self.now()) + ENROLLMENT_GRANT_TTL))
        return grant

    def start_enrollment(self, *, grant, principal):
        """Redeem an explicit operator grant once; bind a separate ticket."""
        principal = _check_identifier(principal)
        if not isinstance(grant, str) or not 32 <= len(grant) <= 128:
            raise ValueError("invalid_enrollment_grant")
        now = int(self.now())
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE enrollment_grants SET used_at=? WHERE grant_hash=? "
                "AND principal=? AND used_at IS NULL AND expires_at>?",
                (now, hashlib.sha256(grant.encode("utf-8")).digest(),
                 principal, now)).rowcount
            if changed != 1:
                raise ValueError("invalid_enrollment_grant")
        intent = self.begin(principal=principal, action="passkey.enroll", target=principal)
        ticket = secrets.token_urlsafe(32)
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO enrollment_tickets VALUES (?, ?, ?, ?, NULL)",
                       (hashlib.sha256(ticket.encode("ascii")).digest(),
                        hashlib.sha256(intent["challenge"].encode("ascii")).digest(),
                        principal, intent["expires_at"]))
        return {**intent, "ticket": ticket}

    def consume_enrollment_ticket(self, *, ticket, challenge, principal):
        """Burn ticket even on mismatch to prevent repeated guessing."""
        principal = _check_identifier(principal)
        if not isinstance(ticket, str) or not 32 <= len(ticket) <= 128:
            return False
        if not isinstance(challenge, str) or not 32 <= len(challenge) <= 128:
            return False
        now = int(self.now())
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            digest = hashlib.sha256(ticket.encode("utf-8")).digest()
            row = db.execute(
                "SELECT challenge_hash,principal,expires_at,used_at FROM "
                "enrollment_tickets WHERE ticket_hash=?", (digest,)).fetchone()
            if row is None:
                return False
            db.execute("UPDATE enrollment_tickets SET used_at=? "
                       "WHERE ticket_hash=? AND used_at IS NULL", (now, digest))
            return bool(row[0] == hashlib.sha256(challenge.encode("utf-8")).digest()
                        and row[1] == principal and row[2] > now and row[3] is None)

    def _record_verified_credential(self, *, credential_id, principal, public_key,
                                    sign_count=0):
        """Persistence sink ONLY for a future validated attestation result.

        Not exposed as CLI/MCP/API; this is no substitute for verifying
        clientDataJSON, authenticatorData, RP hash, attestation and user presence.
        """
        credential_id = _check_identifier(credential_id)
        principal = _check_identifier(principal)
        if not isinstance(public_key, bytes) or not 32 <= len(public_key) <= 4096:
            raise ValueError("invalid_public_key")
        if not isinstance(sign_count, int) or not 0 <= sign_count < 2**32:
            raise ValueError("invalid_sign_counter")
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO credentials VALUES (?, ?, ?, ?, ?, NULL)",
                       (credential_id, principal, public_key, sign_count, int(self.now())))

    def _verified_credential(self, *, credential_id, principal):
        """Read a non-revoked credential for the isolated B2 verifier."""
        credential_id = _check_identifier(credential_id)
        principal = _check_identifier(principal)
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT public_key,sign_count FROM credentials "
                "WHERE credential_id=? AND principal=? AND revoked_at IS NULL",
                (credential_id, principal)).fetchone()

    def _advance_verified_counter(self, *, credential_id, principal, previous, current):
        """Reject counter rollback or a race with revocation/another assertion.

        Synced passkeys may report 0 throughout; WebAuthn accepts this only if
        both counters are 0. The per-ceremony intent has already been burned.
        """
        credential_id = _check_identifier(credential_id)
        principal = _check_identifier(principal)
        if not isinstance(previous, int) or not isinstance(current, int) or (
            previous != 0 or current != 0) and current <= previous:
            raise ValueError("sign_counter_regression")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE credentials SET sign_count=? WHERE credential_id=? "
                "AND principal=? AND sign_count=? AND revoked_at IS NULL",
                (current, credential_id, principal, previous)).rowcount
            if changed != 1:
                raise ValueError("credential_revoked_or_raced")

    def revoke(self, *, credential_id):
        """Internal administrative mutation; caller authentication is B2/C."""
        credential_id = _check_identifier(credential_id)
        with closing(self._connect()) as db, db:
            return db.execute(
                "UPDATE credentials SET revoked_at=? WHERE credential_id=? AND revoked_at IS NULL",
                (int(self.now()), credential_id)).rowcount == 1

    def credential_metadata(self, *, principal):
        """No key bytes or secret material returned."""
        principal = _check_identifier(principal)
        with closing(self._connect()) as db, db:
            return [
                {"credential_id": cid, "added_at": added, "revoked": revoked is not None}
                for cid, added, revoked in db.execute(
                    "SELECT credential_id,added_at,revoked_at FROM credentials WHERE principal=? ORDER BY added_at,credential_id",
                    (principal,))
            ]
