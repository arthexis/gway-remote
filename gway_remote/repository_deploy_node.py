"""Node-local durable deployment admission. Never executes an installer.

An independent root-owned service must validate the SSH forced-command identity
and use this ledger before calling the fixed repository installer.
"""
from __future__ import annotations

import json
import hashlib
import os
import tempfile
from pathlib import Path
import re
import sqlite3
import stat

from .manual_deploy_recipe import repository_installer_argv
from .node_exec_worker import validate_request_id

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_STATES = {"reserved", "running", "succeeded", "failed", "unknown", "already_current"}


class NodeDeploymentLedger:
    def __init__(self, path):
        self.path = Path(path)
        self._check()
    
    def _check(self):
        parent = self.path.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
                or parent.st_mode & 0o077):
            raise PermissionError("unsafe node deployment ledger directory")
        if self.path.is_symlink():
            raise PermissionError("symlink ledger denied")
        if self.path.exists():
            info = self.path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077):
                raise PermissionError("unsafe node deployment ledger")

    def _connect(self):
        self._check()
        old = os.umask(0o077)
        try:
            db = sqlite3.connect(self.path, timeout=10)
        finally:
            os.umask(old)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            request_id TEXT PRIMARY KEY, principal TEXT NOT NULL,
            node TEXT NOT NULL, repository TEXT NOT NULL,
            sha TEXT NOT NULL, state TEXT NOT NULL
        )""")
        return db

    def reserve(self, *, request_id, principal, node, repository, sha):
        validate_request_id(request_id)
        if type(principal) is not str or not principal:
            raise PermissionError("missing authenticated principal")
        if type(sha) is not str or not _SHA.fullmatch(sha):
            raise ValueError("immutable SHA required")
        # Registry and wrapper are validated on the actual target node.
        repository_installer_argv(repository, node, sha)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE request_id=?", (request_id,)).fetchone()
            identity = (principal, node, repository, sha)
            if row:
                if tuple(row[k] for k in ("principal", "node", "repository", "sha")) != identity:
                    raise PermissionError("request ID rebound")
                return {**dict(row), "new": False}
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                       (request_id, *identity, "reserved"))
            return {"request_id": request_id, "principal": principal, "node": node,
                    "repository": repository, "sha": sha, "state": "reserved", "new": True}

    def transition(self, request_id, principal, old, new):
        validate_request_id(request_id)
        if (old, new) not in {("reserved", "running"),
                              ("running", "succeeded"), ("running", "failed"),
                              ("running", "unknown"), ("running", "already_current")}:
            raise ValueError("invalid state transition")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return db.execute(
                "UPDATE jobs SET state=? WHERE request_id=? AND principal=? AND state=?",
                (new, request_id, principal, old)).rowcount == 1


def verify_installed_receipt(path, *, repository, node, sha, digest):
    """Check a trusted, root-owned atomic receipt; never trust checkout HEAD."""
    path = Path(path)
    if not path.is_absolute():
        raise PermissionError("receipt must be absolute")
    for part in (path, *path.parents):
        info = part.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise PermissionError("unsafe receipt path")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
        raise PermissionError("unsafe receipt file")
    record = json.loads(path.read_text(encoding="utf-8"))
    expected = {"repository": repository, "node": node, "sha": sha,
                "manifest_sha256": digest}
    if type(record) is not dict or set(record) != set(expected) or any(
            record[k] != v for k, v in expected.items()):
        raise PermissionError("installed receipt mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}\Z", digest):
        raise ValueError("invalid manifest digest")
    return record


def publish_installed_receipt(path, *, repository, node, sha, manifest_path):
    """Atomically publish a release receipt only after reading its manifest.

    This is a local helper, NOT proof of the active release symlink.
    The caller must separately verify active release identity and that the
    manifest is produced by the repository-owned installer.
    """
    path = Path(path)
    manifest_path = Path(manifest_path)
    if type(sha) is not str or not _SHA.fullmatch(sha):
        raise ValueError("immutable SHA required")
    if repository != "arthexis/odoo-gelectriic" or node != "gway-001":
        raise PermissionError("unapproved installed receipt target")
    for candidate in (path.parent, manifest_path, *manifest_path.parents):
        info = candidate.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise PermissionError("unsafe receipt or manifest location")
    if not stat.S_ISREG(manifest_path.lstat().st_mode):
        raise PermissionError("manifest is not a regular file")
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    record = {"repository": repository, "node": node, "sha": sha,
              "manifest_sha256": digest}
    encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temp = None
    try:
        fd, name = tempfile.mkstemp(prefix=".installed-", dir=path.parent)
        temp = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        temp = None
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return record
