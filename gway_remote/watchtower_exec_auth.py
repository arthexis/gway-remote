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
from . import node_registry_inventory

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
    """Execute-scoped authorization with current enrollment checks and durable deduplication."""

    def __init__(self, ledger, approvals, relay, *, enabled=False):
        self.ledger = ledger
        self.relay = relay
        self.enabled = enabled

    def _allow(self, principal):
        if not self.enabled or not self.relay.enabled:
            raise PermissionError("remote execution disabled")
        if type(principal) is not str or not _KEY_ID.fullmatch(principal):
            raise PermissionError("invalid execute principal")

    def _current_eligibility(self, node):
        """Fail closed against the root-published current enrollment projection."""
        pinned = self.relay.transport.node
        inventory = node_registry_inventory.load()
        rows = [r for r in inventory["nodes"] if r["node"] == node]
        if (len(rows) != 1 or node != pinned.node or
                rows[0]["registered"] is not True or
                rows[0]["identity_verified"] is not True or
                rows[0]["execute_eligible"] is not True or
                rows[0]["reachable"] != "reachable" or
                rows[0]["address"] != pinned.wireguard_address):
            raise PermissionError("current enrolled execution eligibility denied")

    def exec(self, *, principal, request_id, node, command):
        self._allow(principal)
        validate_request_id(request_id)
        validate_command(node, command)
        if node != self.relay.transport.node.node:
            raise PermissionError("node not eligible for this transport")
        self._current_eligibility(node)
        # First insertion wins. Retrying an already known request ID never
        # redispatches, even when its status is uncertain or the process restarted.
        from datetime import timedelta
        try:
            prior = self.ledger.get(request_id)
        except ValueError as exc:
            if str(exc) != "request not found":
                raise
            prior = None
        if prior is not None:
            from .watchtower_exec_transport import _digest
            if (prior["node"] != node or prior["principal"] != principal or
                    prior["host_key_sha256"] != self.relay.transport.node.host_key_sha256 or
                    prior["command_sha256"] != _digest(node, command, principal,
                        self.relay.transport.node.host_key_sha256)):
                raise PermissionError("request ID already bound to another job")
            return {"request_id": request_id, "node": node, "status": prior["state"]}
        expiry = (_now() + timedelta(seconds=120)).isoformat()
        self.ledger.reserve(request_id=request_id, node=node, command=command,
                            principal=principal,
                            host_key_sha256=self.relay.transport.node.host_key_sha256,
                            expires_at=expiry)
        self._current_eligibility(node)
        return {"request_id": request_id, "node": node,
                "status": self.relay.dispatch(request_id)}

    def _owned(self, principal, request_id):
        self._allow(principal)
        record = self.ledger.get(request_id)
        if record["principal"] != principal:
            raise PermissionError("request belongs to another principal")
        return record

    def result(self, *, principal, request_id, cursor=0):
        self._owned(principal, request_id)
        return self.relay.result(request_id, cursor)

    def cancel(self, *, principal, request_id):
        self._owned(principal, request_id)
        return self.relay.cancel(request_id)
