"""B2b-3: operator-issued one-use execution approvals, never MCP-issued.

An execute-scope bearer is necessary but insufficient: a trusted local operator
must issue a command-specific one-time approval against the pinned node identity.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets
import sqlite3

from .node_exec_contract import validate_command
from .node_exec_worker import validate_request_id
from .watchtower_exec_transport import RequestLedger, DormantRelay, HEX_SHA256

_KEY_ID = re.compile(r"[0-9a-f]{24}")


def _now():
    return datetime.now(timezone.utc)


class ExecutionApprovals:
    def __init__(self, ledger: RequestLedger):
        self.ledger = ledger

    def _table(self, db):
        db.execute("""CREATE TABLE IF NOT EXISTS exec_approvals (
            digest TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
            principal TEXT NOT NULL, node TEXT NOT NULL,
            command TEXT NOT NULL, host_sha256 TEXT NOT NULL,
            expires_at TEXT NOT NULL, issued_by TEXT NOT NULL,
            consumed_at TEXT
        )""")

    def issue(self, *, principal, node, command, request_id, host_sha256,
              issued_by, ttl_seconds=90):
        validate_request_id(request_id)
        validate_command(node, command)
        if node != "gway-001" or not isinstance(principal, str) or not _KEY_ID.fullmatch(principal):
            raise ValueError("unapproved execution identity")
        if type(host_sha256) is not str or not HEX_SHA256.fullmatch(host_sha256):
            raise ValueError("invalid enrolled host identity")
        if not isinstance(issued_by, str) or not 1 <= len(issued_by) <= 100:
            raise ValueError("operator identity required")
        if type(ttl_seconds) is not int or not 10 <= ttl_seconds <= 120:
            raise ValueError("invalid approval ttl")
        approval = secrets.token_urlsafe(32)
        expiry = (_now() + timedelta(seconds=ttl_seconds)).isoformat()
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._table(db)
            db.execute("""INSERT INTO exec_approvals
                (digest,request_id,principal,node,command,host_sha256,
                 expires_at,issued_by,consumed_at) VALUES (?,?,?,?,?,?,?,?,NULL)""",
                (hashlib.sha256(approval.encode()).hexdigest(),request_id,principal,
                 node,command,host_sha256,expiry,issued_by))
        return {"approval":approval,"request_id":request_id,"expires_at":expiry}

    def consume(self, *, approval, principal, request_id, node, command, host_sha256):
        validate_request_id(request_id)
        validate_command(node,command)
        if type(approval) is not str or len(approval) > 128:
            raise PermissionError("missing execution approval")
        digest = hashlib.sha256(approval.encode()).hexdigest()
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._table(db)
            row = db.execute("SELECT * FROM exec_approvals WHERE digest=?", (digest,)).fetchone()
            if (row is None or row["consumed_at"] is not None
                    or row["principal"] != principal or row["request_id"] != request_id
                    or row["node"] != node or row["command"] != command
                    or row["host_sha256"] != host_sha256
                    or datetime.fromisoformat(row["expires_at"]) <= _now()):
                raise PermissionError("execution approval invalid or already used")
            db.execute("UPDATE exec_approvals SET consumed_at=? WHERE digest=? AND consumed_at IS NULL",
                       (_now().isoformat(),digest))
            return row["expires_at"]


class AuthorizedExecution:
    """Policy facade. Caller identity MUST come from a verified execute bearer."""

    def __init__(self, ledger, approvals, relay, *, enabled=False):
        self.ledger = ledger
        self.approvals = approvals
        self.relay = relay
        self.enabled = enabled

    def _allow(self, principal):
        if not self.enabled or not self.relay.enabled:
            raise PermissionError("remote execution disabled")
        if type(principal) is not str or not _KEY_ID.fullmatch(principal):
            raise PermissionError("invalid execute principal")

    def exec(self, *, principal, request_id, node, command, approval):
        self._allow(principal)
        if node != self.relay.transport.node.node:
            raise PermissionError("node not approved")
        expiry = self.approvals.consume(
            approval=approval,principal=principal,request_id=request_id,
            node=node,command=command,
            host_sha256=self.relay.transport.node.host_key_sha256)
        self.ledger.reserve(request_id=request_id,node=node,command=command,
                            principal=principal,
                            host_key_sha256=self.relay.transport.node.host_key_sha256,
                            expires_at=expiry)
        return {"request_id":request_id, "node":node,
                "status":self.relay.dispatch(request_id)}

    def _owned(self, principal, request_id):
        self._allow(principal)
        record = self.ledger.get(request_id)
        if record["principal"] != principal:
            raise PermissionError("request belongs to another principal")
        return record

    def result(self, *, principal, request_id, cursor=0):
        self._owned(principal,request_id)
        return self.relay.result(request_id,cursor)

    def cancel(self, *, principal, request_id):
        self._owned(principal,request_id)
        return self.relay.cancel(request_id)
