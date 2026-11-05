"""Watchtower-only admission and durable receipt contract for manual deployments.

This module does not execute shell commands. A privileged, fixed-recipe
deployment service must be installed separately before dispatch is enabled.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from datetime import datetime, timezone

from .manual_deploy_policy import validate_deployment
from .node_exec_worker import validate_request_id

SHA = re.compile(r"[0-9a-f]{40}\Z")
STATES = frozenset({"reserved", "running", "succeeded", "failed", "unknown", "already_current"})


def _now():
    return datetime.now(timezone.utc).isoformat()


def authorize_deploy(repository, node, revision, *, inventory, resolve_sha):
    """Validate authorization and current attested identity before resolving a SHA.

    inventory is a trusted root-published snapshot; resolve_sha is a trusted
    Git resolver restricted to the approved repository. Neither is caller input.
    """
    request = validate_deployment(repository, node, revision)
    rows = [row for row in inventory["nodes"] if row.get("node") == node]
    if (len(rows) != 1 or rows[0].get("registered") is not True
            or rows[0].get("identity_verified") is not True
            or rows[0].get("reachable") != "reachable"):
        raise PermissionError("deployment target is not currently attested and reachable")
    sha = resolve_sha(repository, revision)
    if type(sha) is not str or not SHA.fullmatch(sha):
        raise ValueError("resolver did not return an immutable commit SHA")
    if revision != "main" and revision != sha:
        raise ValueError("resolved revision differs from requested commit")
    return {**request, "sha": sha}


class DeploymentReceipts:
    """Private SQLite ledger; request IDs are never rebound or silently replayed."""

    def __init__(self, path):
        self.path = Path(path)
        self._check_parent()

    def _check_parent(self):
        info = self.path.parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077):
            raise PermissionError("deployment receipt directory must be private")
        if self.path.is_symlink():
            raise PermissionError("deployment receipt file cannot be symlink")

    def _connect(self):
        self._check_parent()
        if self.path.exists():
            info = self.path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077):
                raise PermissionError("unsafe deployment receipt file")
        old = os.umask(0o077)
        try:
            db = sqlite3.connect(self.path, timeout=10)
        finally:
            os.umask(old)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            request_id TEXT PRIMARY KEY, principal TEXT NOT NULL,
            repository TEXT NOT NULL, node TEXT NOT NULL,
            sha TEXT NOT NULL, state TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        return db

    def reserve(self, request_id, principal, approved):
        validate_request_id(request_id)
        if type(principal) is not str or not principal:
            raise PermissionError("missing deployment principal")
        if not isinstance(approved, dict) or not SHA.fullmatch(approved["sha"]):
            raise ValueError("deployment request not authorized")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE request_id=?", (request_id,)).fetchone()
            identity = (principal, approved["repository"], approved["node"], approved["sha"])
            if row is not None:
                if tuple(row[k] for k in ("principal", "repository", "node", "sha")) != identity:
                    raise PermissionError("deployment request ID is bound to another job")
                return dict(row)
            now = _now()
            db.execute("""INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)""",
                       (request_id, *identity, "reserved", now, now))
            return dict(db.execute("SELECT * FROM jobs WHERE request_id=?", (request_id,)).fetchone())

    def transition(self, request_id, expected, state):
        validate_request_id(request_id)
        if state not in STATES or expected not in STATES:
            raise ValueError("invalid deployment state")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE jobs SET state=?, updated_at=? WHERE request_id=? AND state=?",
                (state, _now(), request_id, expected)).rowcount
            return changed == 1

    def status(self, request_id, principal):
        validate_request_id(request_id)
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE request_id=?", (request_id,)).fetchone()
            if row is None or row["principal"] != principal:
                raise PermissionError("deployment receipt not accessible")
            return dict(row)
