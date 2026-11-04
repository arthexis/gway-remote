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
TOKEN_PREFIX = "gwr_"
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
            if not parent or parent[3] is not None or parent[2] <= int(time.time()) or parent[1] != scope:
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
                    and row[1] == required_scope and hmac.compare_digest(row[0], supplied))

    def revoke(self, key_id):
        if not isinstance(key_id, str) or len(key_id) != 24:
            raise ValueError("invalid_id")
        with self._db() as con:
            return con.execute("UPDATE credentials SET revoked_at=? WHERE key_id=? AND revoked_at IS NULL",
                               (int(time.time()), key_id)).rowcount == 1


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
            if not ancestor or ancestor[0] != row[1] or ancestor[1] <= int(time.time()) or ancestor[2] is not None:
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
                    and row[1] == required_scope and hmac.compare_digest(row[0], supplied))

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
