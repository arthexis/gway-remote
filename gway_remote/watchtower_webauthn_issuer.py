"""C3: passkey-gated bearer issuance, isolated from active services.

Only the dedicated trusted administrator can construct this issuer.
No source here installs a service, enables HTTP routing or auto-enrolls admins.
"""
from contextlib import closing
import os
import sqlite3
import time
from pathlib import Path

from .mcp_bearer import SCOPES
from .watchtower_webauthn_ledger import _check_identifier
from .watchtower_webauthn_verify import verify_assertion

MAX_LIFETIME = 30 * 86400
ISSUES_PER_HOUR = 3
TARGETS = {"gway:read": "gway-read", "gway:execute": "gway-execute"}


class IssuanceLedger:
    """Persistent limit and non-secret receipt, separate from token digests."""

    def __init__(self, path, *, now=None):
        self.path = Path(path)
        self.now = now or time.time

    def _db(self):
        if self.path.is_symlink():
            raise ValueError("unsafe_issuance_ledger")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.exists() and (not self.path.is_file() or
                                   self.path.stat().st_mode & 0o077):
            raise ValueError("unsafe_issuance_permissions")
        con = sqlite3.connect(self.path, timeout=5)
        try:
            os.chmod(self.path, 0o600)
            con.execute("""CREATE TABLE IF NOT EXISTS receipts(
                id INTEGER PRIMARY KEY, principal TEXT NOT NULL,
                credential_id TEXT NOT NULL, scope TEXT NOT NULL,
                timestamp INTEGER NOT NULL, bearer_id TEXT)""")
            con.execute("CREATE INDEX IF NOT EXISTS receipts_rate "
                        "ON receipts(principal,timestamp)")
            con.commit()
        except Exception:
            con.close()
            raise
        return con

    def reserve(self, *, principal, credential_id, scope):
        principal = _check_identifier(principal)
        credential_id = _check_identifier(credential_id)
        if scope not in TARGETS:
            raise ValueError("invalid_scope")
        now = int(self.now())
        with closing(self._db()) as con, con:
            con.execute("BEGIN IMMEDIATE")
            count = con.execute(
                "SELECT count(*) FROM receipts WHERE principal=? AND timestamp>?",
                (principal, now - 3600)).fetchone()[0]
            if count >= ISSUES_PER_HOUR:
                raise PermissionError("issuance_rate_limit")
            return con.execute(
                "INSERT INTO receipts (principal,credential_id,scope,timestamp,bearer_id) "
                "VALUES (?,?,?,?,NULL)",
                (principal, credential_id, scope, now)).lastrowid

    def record(self, *, receipt_id, bearer_id):
        bearer_id = _check_identifier(bearer_id)
        with closing(self._db()) as con, con:
            updated = con.execute(
                "UPDATE receipts SET bearer_id=? WHERE id=? AND bearer_id IS NULL",
                (bearer_id, receipt_id)).rowcount
            if updated != 1:
                raise ValueError("invalid_issuance_receipt")


class WatchtowerBearerIssuer:
    """Only an in-process, verified WebAuthn assertion can mint a bearer.

    Construction requires an explicit administrative principal allowlist
    from protected configuration. Never instantiate in the public MCP
    verifier, Mobile API or existing OAuth linker.
    """

    def __init__(self, *, credentials, registry, receipts, administrators):
        admins = frozenset(_check_identifier(value) for value in administrators)
        if not admins:
            raise ValueError("explicit_administrators_required")
        self.credentials = credentials
        self.registry = registry
        self.receipts = receipts
        self.admins = admins

    def issue(self, *, principal, scope, lifetime, challenge, credential):
        if principal not in self.admins:
            raise PermissionError("administrator_required")
        if scope not in SCOPES or scope not in TARGETS:
            raise ValueError("invalid_scope")
        if type(lifetime) is not int or not 60 <= lifetime <= MAX_LIFETIME:
            raise ValueError("invalid_lifetime")

        # This consumes the exact action-bound challenge and validates
        # the FIDO2 signature, origin, RP ID, UV, revocation and counter.
        # No reusable "verified:true" response is accepted here.
        assertion = verify_assertion(
            self.credentials, challenge=challenge, principal=principal,
            action="bearer.issue", target=TARGETS[scope],
            credential=credential)
        # Recheck revocation immediately before entering the issuer boundary.
        if self.credentials._verified_credential(
                credential_id=assertion.credential_id, principal=principal) is None:
            raise PermissionError("credential_revoked")

        receipt_id = self.receipts.reserve(
            principal=principal, credential_id=assertion.credential_id, scope=scope)
        # Only this validated code path opts into direct operator approval.
        # The registry still stores *only* the token digest, never plaintext.
        bearer = self.registry.issue(
            scope=scope, lifetime=lifetime, operator_approved=True)
        key_id = bearer.split("_", 2)[1]
        self.receipts.record(receipt_id=receipt_id, bearer_id=key_id)
        # One-time result; no persistent plaintext copy or print/log.
        return {"bearer": bearer, "bearer_id": key_id,
                "scope": scope, "expires_in": lifetime}
