"""Private, revocable per-device Mobile API credentials.

Separate from Watchtower MCP OAuth bearers and the legacy mobile API secret.
Only this node's installation user may own the 0700 directory / 0600 DB.
One-time plaintext is returned only to an in-process, node-owned provisioner.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time

ID = re.compile(r"[0-9a-f]{24}\Z")
LABEL = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")
TOKEN = re.compile(r"gwymob1_([0-9a-f]{24})_([A-Za-z0-9_-]{43})\Z")
SCOPES = frozenset(("read", "execute"))


class DeviceCredentialError(RuntimeError):
    pass


def default_path():
    return Path.home() / ".config" / "gway-remote" / "mobile-device-credentials.sqlite3"


class DeviceCredentials:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_path()

    def _check_owner(self, *, create=False):
        parent = self.path.parent
        if create and not parent.exists():
            parent.mkdir(mode=0o700, parents=True)
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077):
            raise DeviceCredentialError("unsafe_mobile_credential_directory")
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return False
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise DeviceCredentialError("unsafe_mobile_credential_file")
        return True

    def _open(self, *, write=False):
        found = self._check_owner(create=write)
        if not found and not write:
            return None
        old = os.umask(0o077)
        try:
            conn = sqlite3.connect(
                str(self.path) if write else self.path.as_uri() + "?mode=ro",
                uri=not write, timeout=3,
            )
        finally:
            os.umask(old)
        try:
            if write:
                if not self._check_owner():
                    raise DeviceCredentialError("credential_file_not_created")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS devices ("
                    "id TEXT PRIMARY KEY, label TEXT NOT NULL, scope TEXT NOT NULL, "
                    "token_sha256 TEXT NOT NULL, expires_at INTEGER NOT NULL, "
                    "revoked INTEGER NOT NULL DEFAULT 0)"
                )
                conn.commit()
        except Exception:
            conn.close()
            raise
        return conn

    def issue(self, *, label, scope="read", days=30, now=None):
        if type(label) is not str or not LABEL.fullmatch(label):
            raise ValueError("invalid_device_label")
        if type(scope) is not str or scope not in SCOPES or type(days) is not int or not 1 <= days <= 90:
            raise ValueError("invalid_device_credential_policy")
        current = int(time.time() if now is None else now)
        identifier = secrets.token_hex(12)
        secret = secrets.token_urlsafe(32)
        token = f"gwymob1_{identifier}_{secret}"
        if not TOKEN.fullmatch(token):
            raise DeviceCredentialError("random_token_generation_failed")
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        expires = current + days * 86400
        conn = self._open(write=True)
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute(
                    "SELECT 1 FROM devices WHERE label=? AND revoked=0 AND expires_at>?",
                    (label, current),
                ).fetchone():
                    raise DeviceCredentialError("active_device_credential_exists")
                conn.execute(
                    "INSERT INTO devices (id,label,scope,token_sha256,expires_at) "
                    "VALUES (?,?,?,?,?)",
                    (identifier, label, scope, digest, expires),
                )
        finally:
            conn.close()
        return {"id": identifier, "token": token, "scope": scope, "expires_at": expires}

    def verify(self, token, *, now=None):
        if type(token) is not str:
            return None
        match = TOKEN.fullmatch(token)
        if not match:
            return None
        try:
            conn = self._open(write=False)
            if conn is None:
                return None
            try:
                row = conn.execute(
                    "SELECT token_sha256,scope,expires_at,revoked FROM devices WHERE id=?",
                    (match.group(1),),
                ).fetchone()
            finally:
                conn.close()
        except (OSError, sqlite3.Error, DeviceCredentialError):
            return None  # fail closed; legacy bearer stays independent
        if row is None or row[3] or row[2] <= int(time.time() if now is None else now):
            return None
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        return row[1] if row[1] in SCOPES and hmac.compare_digest(digest, row[0]) else None

    def revoke(self, identifier):
        if type(identifier) is not str or not ID.fullmatch(identifier):
            raise ValueError("invalid_device_credential_id")
        conn = self._open(write=True)
        try:
            with conn:
                result = conn.execute(
                    "UPDATE devices SET revoked=1 WHERE id=? AND revoked=0",
                    (identifier,),
                )
            return result.rowcount == 1
        finally:
            conn.close()

    def list_public(self):
        conn = self._open(write=False)
        if conn is None:
            return []
        try:
            return [
                {"id": row[0], "label": row[1], "scope": row[2],
                 "expires_at": row[3], "revoked": bool(row[4])}
                for row in conn.execute(
                    "SELECT id,label,scope,expires_at,revoked FROM devices ORDER BY label,id"
                )
            ]
        finally:
            conn.close()


def main():
    """Local credential inspection and targeted revocation, never issuance."""
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Private Mobile API device credentials")
    actions = parser.add_subparsers(dest="operation", required=True)
    actions.add_parser("list")
    revoke = actions.add_parser("revoke")
    revoke.add_argument("id")
    args = parser.parse_args()
    try:
        registry = DeviceCredentials()
        result = registry.list_public() if args.operation == "list" else {
            "revoked": registry.revoke(args.id)
        }
        print(json.dumps(result, sort_keys=True))
    except (OSError, sqlite3.Error, ValueError, DeviceCredentialError):
        print(json.dumps({"status": "unavailable"}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
