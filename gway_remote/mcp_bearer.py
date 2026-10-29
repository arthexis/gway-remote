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
import stat
from pathlib import Path

SCOPES = frozenset({"gway:read"})
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
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.exists() and (not self.path.is_file() or self.path.stat().st_mode & 0o077):
            raise ValueError("unsafe_registry_permissions")
        con = sqlite3.connect(self.path, timeout=10)
        try:
            os.chmod(self.path, 0o600)
            con.execute("""CREATE TABLE IF NOT EXISTS credentials (
                key_id TEXT PRIMARY KEY, digest BLOB NOT NULL,
                scope TEXT NOT NULL, expires_at INTEGER NOT NULL,
                revoked_at INTEGER)""")
            con.commit()
        except Exception:
            con.close()
            raise
        return con

    def issue(self, *, scope="gway:read", lifetime=DEFAULT_LIFETIME):
        if scope not in SCOPES or not isinstance(lifetime, int) or not 60 <= lifetime <= 90 * 86400:
            raise ValueError("invalid_scope_or_lifetime")
        key_id = secrets.token_hex(12)
        secret = secrets.token_urlsafe(32)
        credential = TOKEN_PREFIX + key_id + "_" + secret
        with self._db() as con:
            con.execute("INSERT INTO credentials VALUES (?, ?, ?, ?, NULL)",
                        (key_id, _digest(secret), scope, int(time.time()) + lifetime))
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
    if path.stat().st_mode & 0o077:
        raise ValueError("unsafe_registry_permissions")
    with sqlite3.connect("file:" + str(path.resolve()) + "?mode=ro", uri=True, timeout=3) as con:
        return con.execute("SELECT digest,scope,expires_at,revoked_at FROM credentials WHERE key_id=?",
                           (key_id,)).fetchone()


class BearerVerifier:
    """Gateway-side capability: verify only; no issue, revoke, or schema creation."""
    def __init__(self, path):
        self.path = Path(path)

    def verify(self, credential, *, required_scope="gway:read"):
        if required_scope != "gway:read" or not isinstance(credential, str):
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
