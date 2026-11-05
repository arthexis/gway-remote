"""Console-issued scoped bearer credentials for the read-only MCP gateway.

The SQLite registry is local to Watchtower. No shell execution or broad GWAY
operation resolution is exposed. Production routing remains separately gated.
"""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from pathlib import Path

SCOPES = frozenset({"gway:read", "gway:execute"})
COMBINED_SCOPE = "gway:execute gway:read"


def _scope_grants(stored, required):
    """Legacy single-scope rows stay unchanged; combined grants are explicit."""
    return (required in SCOPES and (stored == required or stored == COMBINED_SCOPE)
            or required == COMBINED_SCOPE and stored == COMBINED_SCOPE)

TOKEN_PREFIX = "gwr_"
REFRESH_PREFIX = "gwf_"
DEFAULT_LIFETIME = 30 * 86400


def _digest(secret):
    return hashlib.sha256(secret.encode("ascii")).digest()


class BearerRegistry:
    def __init__(self, path):
        self.path = Path(path)

    def _db(self):
        if self.path.is_symlink():
            raise ValueError("unsafe_registry_path")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        if self.path.exists() and (not self.path.is_file() or self.path.stat().st_mode & 0o007):
            raise ValueError("unsafe_registry_permissions")
        con = sqlite3.connect(self.path, timeout=10)
        try:
            os.chmod(self.path, 0o640)
            con.execute("""CREATE TABLE IF NOT EXISTS credentials (
                key_id TEXT PRIMARY KEY, digest BLOB NOT NULL,
                scope TEXT NOT NULL, expires_at INTEGER NOT NULL,
                revoked_at INTEGER)""")
            con.execute("CREATE TABLE IF NOT EXISTS delegations (key_id TEXT PRIMARY KEY, parent_id TEXT NOT NULL)")
            con.execute("""CREATE TABLE IF NOT EXISTS oauth_refresh (
                key_id TEXT PRIMARY KEY, digest BLOB NOT NULL,
                family_id TEXT NOT NULL, client_id TEXT NOT NULL,
                scope TEXT NOT NULL, expires_at INTEGER NOT NULL,
                consumed_at INTEGER)""")
            con.commit()
        except Exception:
            con.close()
            raise
        return con

    def issue(self, *, scope="gway:read", lifetime=DEFAULT_LIFETIME, parent_id=None, operator_approved=False):
        if scope not in SCOPES or not isinstance(lifetime, int) or not 60 <= lifetime <= 90 * 86400:
            raise ValueError("invalid_scope_or_lifetime")
        # Never let existing OAuth/delegation code mint execute credentials.
        # Only an explicit trusted console path may opt in.
        if scope == "gway:execute" and operator_approved is not True and parent_id is None:
            raise PermissionError("execution scope requires direct operator issuance")
        expires_at = int(time.time()) + lifetime
        if parent_id is not None:
            parent = _lookup(self.path, parent_id)
            if not parent or parent[3] is not None or parent[2] <= int(time.time()) or not _scope_grants(parent[1], scope):
                raise ValueError("invalid_parent_credential")
            expires_at = min(expires_at, parent[2])
        key_id = secrets.token_hex(12)
        secret = secrets.token_urlsafe(32)
        credential = TOKEN_PREFIX + key_id + "_" + secret
        with self._db() as con:
            con.execute("INSERT INTO credentials VALUES (?, ?, ?, ?, NULL)",
                        (key_id, _digest(secret), scope, expires_at))
            if parent_id is not None:
                con.execute("INSERT INTO delegations VALUES (?, ?)", (key_id, parent_id))
        return credential


    def issue_combined(self, *, lifetime=86400, operator_approved=False):
        """Issue one explicitly approved, combined read+execute parent token.

        The plaintext is returned once; only a digest is persisted. This method
        must only be invoked by Watchtower's verified administrative issuer.
        """
        if operator_approved is not True:
            raise PermissionError("direct_administrator_approval_required")
        if type(lifetime) is not int or not 60 <= lifetime <= 30 * 86400:
            raise ValueError("invalid_lifetime")
        key_id = secrets.token_hex(12)
        secret = secrets.token_urlsafe(32)
        with self._db() as con:
            con.execute("INSERT INTO credentials VALUES (?, ?, ?, ?, NULL)",
                        (key_id, _digest(secret), COMBINED_SCOPE, int(time.time()) + lifetime))
        return TOKEN_PREFIX + key_id + "_" + secret

    def issue_oauth_pair(self, *, parent_id, scope, client_id):
        """Mint access and rotating refresh tokens bound to a hidden revocable family."""
        if scope not in SCOPES | {COMBINED_SCOPE} or not isinstance(client_id, str) or not client_id:
            raise ValueError("invalid_grant")
        now = int(time.time())
        parent = _lookup(self.path, parent_id)
        if not parent or not _scope_grants(parent[1], scope) or parent[2] <= now or parent[3] is not None:
            raise ValueError("invalid_grant")
        with self._db() as con:
            con.execute("BEGIN IMMEDIATE")
            parent = _lookup(self.path, parent_id)
            if not parent or not _scope_grants(parent[1], scope) or parent[2] <= now or parent[3] is not None:
                raise ValueError("invalid_grant")
            family_id, _ = _store_oauth_credential(con, scope, parent[2], parent_id)
            _, access = _store_oauth_credential(
                con, scope, min(now + 3600, parent[2]), family_id)
            refresh = _store_oauth_refresh(con, family_id, client_id, scope, parent[2])
        return {"access_token": access, "refresh_token": refresh,
                "token_type": "Bearer", "expires_in": max(0, min(now + 3600, parent[2]) - now),
                "scope": scope}

    def rotate_oauth_refresh(self, *, token, client_id):
        """One-use refresh rotation; verified replay revokes all family access tokens."""
        if not isinstance(token, str) or not isinstance(client_id, str):
            raise ValueError("invalid_grant")
        parts = token.split("_", 2)
        if len(parts) != 3 or parts[0] != "gwf" or len(parts[1]) != 24:
            raise ValueError("invalid_grant")
        try:
            int(parts[1], 16)
            digest = _digest(parts[2])
        except (ValueError, UnicodeError):
            raise ValueError("invalid_grant") from None
        now = int(time.time())
        replay = False
        with self._db() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT digest,family_id,client_id,scope,expires_at,consumed_at "
                "FROM oauth_refresh WHERE key_id=?", (parts[1],)).fetchone()
            if (not row or not hmac.compare_digest(row[0], digest)
                    or row[2] != client_id or row[4] <= now):
                raise ValueError("invalid_grant")
            if row[5] is not None:
                con.execute("UPDATE credentials SET revoked_at=? "
                            "WHERE key_id=? AND revoked_at IS NULL", (now, row[1]))
                replay = True
            else:
                family = _lookup(self.path, row[1])
                if (not family or family[1] != row[3] or
                        family[2] <= now or family[3] is not None):
                    raise ValueError("invalid_grant")
                changed = con.execute("UPDATE oauth_refresh SET consumed_at=? "
                    "WHERE key_id=? AND consumed_at IS NULL", (now, parts[1]))
                if changed.rowcount != 1:
                    raise ValueError("invalid_grant")
                _, access = _store_oauth_credential(
                    con, row[3], min(now + 3600, row[4]), row[1])
                refresh = _store_oauth_refresh(con, row[1], client_id, row[3], row[4])
        if replay:
            raise ValueError("invalid_grant")
        return {"access_token": access, "refresh_token": refresh,
                "token_type": "Bearer", "expires_in": max(0, min(now + 3600, row[4]) - now),
                "scope": row[3]}

    def verify(self, credential, *, required_scope="gway:read"):
        if required_scope not in SCOPES or not isinstance(credential, str):
            return False
        parts = credential.split("_", 2)
        if len(parts) != 3 or parts[0] != "gwr" or len(parts[1]) != 24:
            return False
        try:
            int(parts[1], 16)
            supplied = _digest(parts[2])
        except (UnicodeError, ValueError):
            return False
        try:
            row = _lookup(self.path, parts[1])
        except (OSError, sqlite3.Error, ValueError):
            return False
        return bool(row and row[3] is None and row[2] > int(time.time())
                    and _scope_grants(row[1], required_scope) and hmac.compare_digest(row[0], supplied))

    def revoke(self, key_id):
        if not isinstance(key_id, str) or len(key_id) != 24:
            raise ValueError("invalid_id")
        with self._db() as con:
            return con.execute("UPDATE credentials SET revoked_at=? WHERE key_id=? AND revoked_at IS NULL",
                               (int(time.time()), key_id)).rowcount == 1



def _store_oauth_credential(con, scope, expires_at, parent_id):
    key_id = secrets.token_hex(12)
    secret = secrets.token_urlsafe(32)
    con.execute("INSERT INTO credentials VALUES (?, ?, ?, ?, NULL)",
                (key_id, _digest(secret), scope, expires_at))
    con.execute("INSERT INTO delegations VALUES (?, ?)", (key_id, parent_id))
    return key_id, TOKEN_PREFIX + key_id + "_" + secret


def _store_oauth_refresh(con, family_id, client_id, scope, expires_at):
    key_id = secrets.token_hex(12)
    secret = secrets.token_urlsafe(32)
    con.execute("INSERT INTO oauth_refresh VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (key_id, _digest(secret), family_id, client_id, scope, expires_at))
    return REFRESH_PREFIX + key_id + "_" + secret

def _lookup(path, key_id):
    """Read-only SQLite lookup; never creates files or mutates the registry."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("invalid_registry")
    if path.stat().st_mode & 0o007:
        raise ValueError("unsafe_registry_permissions")
    with sqlite3.connect("file:" + str(path.resolve()) + "?mode=ro", uri=True, timeout=3) as con:
        row = con.execute("SELECT digest,scope,expires_at,revoked_at FROM credentials WHERE key_id=?",
                          (key_id,)).fetchone()
        # Legacy console-only registries have no delegation table. New OAuth
        # credentials retain their proof lineage, so revocation/expiry of any
        # ancestor invalidates descendants even after service restart.
        if not row or not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='delegations'").fetchone():
            return row
        seen = set()
        current = key_id
        while True:
            if current in seen or len(seen) >= 32:
                return None
            seen.add(current)
            parent = con.execute("SELECT parent_id FROM delegations WHERE key_id=?", (current,)).fetchone()
            if not parent:
                return row
            current = parent[0]
            ancestor = con.execute("SELECT scope,expires_at,revoked_at FROM credentials WHERE key_id=?", (current,)).fetchone()
            if not ancestor or not _scope_grants(ancestor[0], row[1]) or ancestor[1] <= int(time.time()) or ancestor[2] is not None:
                return None


class BearerVerifier:
    """Gateway-side capability: verify only; no issue, revoke, or schema creation."""
    def __init__(self, path):
        self.path = Path(path)

    def verify(self, credential, *, required_scope="gway:read"):
        if required_scope not in SCOPES or not isinstance(credential, str):
            return False
        parts = credential.split("_", 2)
        if len(parts) != 3 or parts[0] != "gwr" or len(parts[1]) != 24:
            return False
        try:
            int(parts[1], 16)
            supplied = _digest(parts[2])
            row = _lookup(self.path, parts[1])
        except (UnicodeError, ValueError, OSError, sqlite3.Error):
            return False
        return bool(row and row[3] is None and row[2] > int(time.time())
                    and _scope_grants(row[1], required_scope) and hmac.compare_digest(row[0], supplied))

    def execution_principal(self, credential):
        """Stable parent identity across OAuth reconnects; requires valid execute scope."""
        if not self.verify(credential, required_scope="gway:execute"):
            raise PermissionError("execute credential required")
        key_id = credential.split("_", 2)[1]
        with sqlite3.connect("file:" + str(self.path.resolve()) + "?mode=ro",
                             uri=True, timeout=3) as db:
            seen = set()
            current = key_id
            for _ in range(32):
                if current in seen:
                    raise PermissionError("credential delegation cycle")
                seen.add(current)
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='delegations'").fetchone():
                    return current
                row = db.execute("SELECT parent_id FROM delegations WHERE key_id=?", (current,)).fetchone()
                if row is None:
                    return current
                current = row[0]
            raise PermissionError("credential delegation depth exceeded")
