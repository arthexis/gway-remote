"""M3 B2b-2: dormant Watchtower request ledger and pinned SSH transport.

No MCP tool is registered here. No SSH credential is generated or installed.
A future B2b-3 authorization layer must approve every submit/result/cancel
before calling this private adapter.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess

from .node_exec_contract import validate_command
from .node_exec_worker import validate_request_id

DEFAULT_LEDGER = Path("/var/lib/gway-mcp-exec/requests.sqlite3")
MAX_RECORDS = 100000
HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
ACTIVE_STATES = frozenset({"reserved", "dispatching", "dispatched", "uncertain"})
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "timed_out", "unknown"})
ALL_STATES = ACTIVE_STATES | TERMINAL_STATES


def _now():
    return datetime.now(timezone.utc).isoformat()


def _parse_expiry(value):
    if type(value) is not str:
        raise ValueError("missing expiry")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("invalid expiry") from None
    if dt.tzinfo is None or dt <= datetime.now(timezone.utc):
        raise ValueError("expired request")
    return value


def _digest(node, command, principal, host_key):
    data = json.dumps([node, command, principal, host_key],
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class RequestLedger:
    """Crash-safe one-time dispatch claims. Never re-dispatch uncertain jobs."""

    def __init__(self, path=DEFAULT_LEDGER):
        self.path = Path(path)
        self._check_path()

    def _check_path(self):
        info = self.path.parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or (info.st_mode & 0o077)):
            raise PermissionError("Watchtower execution ledger parent must be private")
        if self.path.is_symlink():
            raise PermissionError("ledger cannot be a symlink")

    @contextmanager
    def connection(self):
        self._check_path()
        if self.path.exists():
            info = self.path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077):
                raise PermissionError("unsafe Watchtower ledger")
        old_mask = os.umask(0o077)
        try:
            db = sqlite3.connect(self.path, timeout=10)
        finally:
            os.umask(old_mask)
        db.row_factory = sqlite3.Row
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS requests (
                request_id TEXT PRIMARY KEY,
                node TEXT NOT NULL,
                principal TEXT NOT NULL,
                host_key_sha256 TEXT NOT NULL,
                command_sha256 TEXT NOT NULL,
                command TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, *, request_id, node, command, principal,
                host_key_sha256, expires_at):
        validate_request_id(request_id)
        validate_command(node, command)
        if type(principal) is not str or not principal or len(principal) > 256:
            raise ValueError("invalid principal")
        if type(host_key_sha256) is not str or not HEX_SHA256.fullmatch(host_key_sha256):
            raise ValueError("invalid pinned host identity")
        identity_digest = _digest(node, command, principal, host_key_sha256)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM requests WHERE request_id=?",
                                  (request_id,)).fetchone()
            if existing is not None:
                if (existing["node"] != node or existing["principal"] != principal
                        or existing["host_key_sha256"] != host_key_sha256
                        or existing["command_sha256"] != identity_digest
                        or existing["expires_at"] != expires_at):
                    raise ValueError("request ID reused for different binding")
                return dict(existing)
            _parse_expiry(expires_at)
            if db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] >= MAX_RECORDS:
                raise RuntimeError("ledger full; fail closed rather than forget IDs")
            now = _now()
            db.execute("""INSERT INTO requests
                (request_id,node,principal,host_key_sha256,command_sha256,
                 command,expires_at,state,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (request_id,node,principal,host_key_sha256,identity_digest,
                 command,expires_at,"reserved",now,now))
            return dict(db.execute("SELECT * FROM requests WHERE request_id=?",
                                   (request_id,)).fetchone())

    def claim_dispatch(self, request_id):
        """Only the first caller wins; crashes leave an uncertain non-replayable claim."""
        validate_request_id(request_id)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM requests WHERE request_id=?",
                             (request_id,)).fetchone()
            if row is None:
                raise ValueError("request not found")
            if row["state"] != "reserved":
                return False
            _parse_expiry(row["expires_at"])
            db.execute("UPDATE requests SET state='dispatching', updated_at=? WHERE request_id=?",
                       (_now(),request_id))
            return True

    def mark_dispatched(self, request_id, *, confirmed):
        validate_request_id(request_id)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM requests WHERE request_id=?",
                             (request_id,)).fetchone()
            if row is None or row["state"] != "dispatching":
                raise ValueError("invalid dispatch transition")
            db.execute("UPDATE requests SET state=?, updated_at=? WHERE request_id=?",
                       ("dispatched" if confirmed else "uncertain", _now(), request_id))

    def record_result_state(self, request_id, state):
        """Persist terminal node result; uncertain jobs may be reconciled."""
        validate_request_id(request_id)
        if state not in TERMINAL_STATES:
            raise ValueError("invalid terminal state")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM requests WHERE request_id=?",
                             (request_id,)).fetchone()
            if row is None or row["state"] == "reserved":
                raise ValueError("request never dispatched")
            if row["state"] in TERMINAL_STATES and row["state"] != state:
                raise ValueError("conflicting terminal state")
            db.execute("UPDATE requests SET state=?, updated_at=? WHERE request_id=?",
                       (state, _now(), request_id))

    def get(self, request_id):
        validate_request_id(request_id)
        with self.connection() as db:
            row = db.execute("SELECT * FROM requests WHERE request_id=?",
                             (request_id,)).fetchone()
        if row is None:
            raise ValueError("request not found")
        return dict(row)


@dataclass(frozen=True)
class PinnedNode:
    """Resolved exclusively from trusted Watchtower enrollment, never an RPC argument."""
    node: str
    wireguard_address: str
    ssh_host_alias: str
    known_hosts: Path
    identity_file: Path
    host_key_sha256: str
    remote_user: str

    def __post_init__(self):
        validate_command(self.node, "true")
        try:
            address = ipaddress.ip_address(self.wireguard_address)
            if address.version != 4 or address not in ipaddress.ip_network("10.0.0.0/8"):
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("invalid enrolled WireGuard endpoint") from None
        if (type(self.ssh_host_alias) is not str
                or not re.fullmatch(r"[a-z0-9-]{1,64}", self.ssh_host_alias)):
            raise ValueError("invalid host alias")
        if not HEX_SHA256.fullmatch(self.host_key_sha256):
            raise ValueError("invalid enrolled host key")
        if type(self.remote_user) is not str or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", self.remote_user):
            raise ValueError("invalid SSH principal")
        for path in (self.known_hosts, self.identity_file):
            info = Path(path).lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise PermissionError("unsafe private SSH material")
        # Verify the pinned public key itself, not just a configurable host alias.
        lines = Path(self.known_hosts).read_text(encoding="ascii").splitlines()
        matches = [line.split() for line in lines
                   if line.strip() and not line.lstrip().startswith("#")
                   and line.split()[0] == self.ssh_host_alias]
        if len(matches) != 1 or len(matches[0]) < 3:
            raise ValueError("missing or ambiguous pinned SSH host key")
        algorithm, encoded = matches[0][1:3]
        if algorithm not in {"ssh-ed25519","ecdsa-sha2-nistp256","rsa-sha2-512","ssh-rsa"}:
            raise ValueError("unsupported SSH host key")
        try:
            fingerprint = hashlib.sha256(base64.b64decode(encoded, validate=True)).hexdigest()
        except (ValueError, TypeError):
            raise ValueError("invalid known_hosts key") from None
        if fingerprint != self.host_key_sha256:
            raise ValueError("host key fingerprint mismatch")


class SSHTransportFailure(OSError):
    """Typed transport failure; delivery of a submit remains uncertain."""

    stage = "ssh_transport"


class SSHTransport:
    """No shell command from clients is included in SSH argv or host selection."""

    def __init__(self, node: PinnedNode, *, run=subprocess.run):
        self.node = node
        self._run = run

    def invoke(self, payload):
        if type(payload) is not dict or payload.get("operation") not in {"submit","result","cancel","limits","provider_list","provider_call","repository_deploy"}:
            raise ValueError("invalid node operation")
        fields = {"submit":{"operation","node","request_id","command"},
                  "result":{"operation","node","request_id","cursor"},
                  "cancel":{"operation","node","request_id"},
                   "limits":{"operation","node","request_id"},
                  "repository_deploy":{"operation","node","request_id","repository","sha"},
                  "provider_list":{"operation","node","request_id"},
                  "provider_call":{"operation","node","request_id","provider","tool","arguments","authorized_scope"}}
        if set(payload) != fields[payload["operation"]]:
            raise ValueError("unexpected transport arguments")
        if payload.get("node") != self.node.node:
            raise ValueError("wrong pinned node")
        validate_request_id(payload.get("request_id"))
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > (65536 if payload["operation"] == "provider_call" else 8192):
            raise ValueError("transport request too large")
        # Forced-command key on node must ignore all SSH_ORIGINAL_COMMAND values.
        argv = ["ssh","-F","/dev/null","-T","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes",
                "-o","IdentitiesOnly=yes","-o","ProxyCommand=none",
                "-o","ClearAllForwardings=yes","-o","PermitLocalCommand=no",
                "-o","ConnectTimeout=5","-o","ConnectionAttempts=1",
                "-o","UserKnownHostsFile=" + str(self.node.known_hosts),
                "-o","HostKeyAlias=" + self.node.ssh_host_alias,
                "-i",str(self.node.identity_file),
                "-l",self.node.remote_user,
                self.node.wireguard_address, "gway-exec-protocol-v1"]
        try:
            completed = self._run(argv,input=raw,capture_output=True,timeout=15,check=True)
        except OSError:
            # Local SSH invocation failed; never classify a remote exit code.
            raise SSHTransportFailure("ssh transport unavailable") from None
        if len(completed.stdout) > 131072:
            raise ValueError("node response exceeds limit")
        result = json.loads(completed.stdout)
        if (type(result) is not dict or result.get("request_id") != payload["request_id"]
                or result.get("node") != self.node.node):
            raise ValueError("incorrect node response identity")
        return result


class MultiNodeTransport:
    """Select only operator-pinned SSH transports, never RPC-supplied endpoints."""

    def __init__(self, transports):
        if not transports or len(transports) != len(set(transports)):
            raise ValueError("invalid pinned transport inventory")
        self.transports = dict(transports)

    def for_node(self, node):
        try:
            return self.transports[node]
        except (KeyError, TypeError):
            raise PermissionError("node has no pinned execution transport") from None

    def invoke(self, payload):
        if type(payload) is not dict:
            raise ValueError("invalid transport payload")
        return self.for_node(payload.get("node")).invoke(payload)


def pinned_transport(transport, node):
    """Resolve a node using the router, retaining legacy single-node adapters."""
    if isinstance(transport, MultiNodeTransport):
        return transport.for_node(node)
    pinned = transport.node
    if pinned.node != node:
        raise PermissionError("node has no pinned execution transport")
    return transport


class DormantRelay:
    """Explicitly disabled until B2b-3 approves authenticated operations."""

    def __init__(self, ledger: RequestLedger, transport: SSHTransport, *, enabled=False):
        self.ledger = ledger
        self.transport = transport
        self.enabled = enabled

    def _authorized_row(self, request_id):
        if not self.enabled:
            raise PermissionError("remote execution disabled pending B2b-3 authorization")
        row = self.ledger.get(request_id)
        if (row["host_key_sha256"] != pinned_transport(self.transport, row["node"]).node.host_key_sha256):
            raise PermissionError("enrolled node identity changed")
        return row

    def dispatch(self, request_id):
        row = self._authorized_row(request_id)
        if not self.ledger.claim_dispatch(request_id):
            return self.ledger.get(request_id)["state"]
        try:
            response = self.transport.invoke({"operation":"submit","node":row["node"],
                                               "request_id":request_id,"command":row["command"]})
        except SSHTransportFailure:
            self.ledger.mark_dispatched(request_id, confirmed=False)
            return {"status": "uncertain", "failure_stage": "ssh_transport"}
        except (OSError, ValueError, subprocess.SubprocessError):
            self.ledger.mark_dispatched(request_id, confirmed=False)
            return "uncertain"
        if (type(response) is dict and response.get("node") == row["node"]
                and response.get("request_id") == request_id
                and response.get("status") == "rejected"
                and response.get("failure_stage") == "worker_readiness"):
            self.ledger.mark_dispatched(request_id, confirmed=False)
            return {"status": "uncertain", "failure_stage": "worker_readiness"}
        if response.get("status") not in {"accepted","queued","running","succeeded"}:
            self.ledger.mark_dispatched(request_id, confirmed=False)
            return "uncertain"
        self.ledger.mark_dispatched(request_id, confirmed=True)
        return "dispatched"

    def result(self, request_id, cursor=0):
        row = self._authorized_row(request_id)
        if row["state"] == "reserved":
            raise ValueError("request not dispatched")
        if type(cursor) is not int or not 0 <= cursor <= 1048576:
            raise ValueError("invalid cursor")
        try:
            data = self.transport.invoke({"operation":"result","node":row["node"],
                                          "request_id":request_id,"cursor":cursor})
        except (OSError, ValueError, subprocess.SubprocessError):
            # A failed read does not prove the remote command never ran.
            # Never replay submit, erase the ledger, or expose SSH stderr.
            return {"node": row["node"], "request_id": request_id,
                    "status": row["state"], "result_available": False,
                    "reason": "node_result_unavailable"}
        if data.get("status") in TERMINAL_STATES:
            self.ledger.record_result_state(request_id, data["status"])
        return data

    def cancel(self, request_id):
        row = self._authorized_row(request_id)
        if row["state"] == "reserved":
            raise ValueError("request not dispatched")
        return self.transport.invoke({"operation":"cancel","node":row["node"],
                                      "request_id":request_id})
