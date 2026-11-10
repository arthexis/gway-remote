"""Authenticated Unix-socket transport for the private Watchtower bridge.

This is intentionally local to Watchtower. Remote node access must be carried
through the separately authenticated and authorized node relay, never by
exposing this Unix socket over an unauthenticated TCP listener.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import hmac
import json
import os
import socket
import socketserver
import stat
import threading
import time
from pathlib import Path

from .mcp_bridge_contract import InvalidBridgeRequest, validate_envelope


class BridgeReadUnavailable(PermissionError):
    """Authenticated, allowlisted read-only diagnostic code."""

    CODES = frozenset({
        "workspace_not_configured", "node_binding_mismatch",
        "repository_not_allowlisted", "workspace_config_invalid",
        "workspace_inspection_unavailable", "deployment_preview_unavailable",
        "deployment_execution_disabled", "deployment_inventory_binding_denied",
        "deployment_pinned_transport_unavailable", "deployment_ssh_unverified",
        "deployment_node_protocol_unavailable", "deployment_declaration_unavailable",
    })

    def __init__(self, code):
        if code not in self.CODES:
            raise ValueError("invalid bridge diagnostic code")
        self.code = code
        super().__init__(code)


MAX_WIRE = 16384
MAX_REPLY = 16384


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sign(key, envelope):
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("bridge key must contain at least 32 bytes")
    return hmac.new(key, canonical(envelope), hashlib.sha256).hexdigest()


def sign_reply(key, request_signature, body):
    """Domain-separated MAC binds a reply to one authenticated request."""
    return sign(key, {"domain": "gway-bridge-reply-v1",
                      "request_signature": request_signature, "body": body})


class AuthenticatedBridge:
    def __init__(self, key, *, audience, dispatch, sessions=None):
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("weak bridge key")
        self.key = key
        self.audience = audience
        self.dispatch = dispatch
        self.sessions = sessions
        self.seen = {}
        self.lock = threading.Lock()

    def process(self, raw, *, now=None):
        if not isinstance(raw, bytes) or len(raw) > MAX_WIRE:
            raise InvalidBridgeRequest("invalid wire size")
        try:
            request = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise InvalidBridgeRequest("invalid JSON") from exc
        if type(request) is not dict or set(request) != ({"envelope", "signature", "session_id"} if self.sessions is not None else {"envelope", "signature"}):
            raise InvalidBridgeRequest("invalid signed request")
        envelope, signature = request["envelope"], request["signature"]
        if type(signature) is not str or len(signature) != 64:
            raise InvalidBridgeRequest("invalid signature")
        signed = {"envelope": envelope, "session_id": request["session_id"]} if self.sessions is not None else envelope
        if not hmac.compare_digest(sign(self.key, signed), signature):
            raise InvalidBridgeRequest("invalid signature")
        validated = validate_envelope(envelope, audience=self.audience, now=now)
        current = int(time.time()) if now is None else now
        with self.lock:
            self.seen = {k: expiry for k, expiry in self.seen.items() if expiry > current}
            nonce = validated["request_id"]
            if nonce in self.seen:
                raise InvalidBridgeRequest("replayed request")
            if len(self.seen) >= 4096:
                raise InvalidBridgeRequest("replay cache full")
            self.seen[nonce] = validated["expires_at"]
        if self.sessions is not None:
            session_id = request["session_id"]
            if type(session_id) is not str or len(session_id) != 48:
                raise InvalidBridgeRequest("invalid session ID")
            return self.sessions.dispatch(session_id, validated)
        return self.dispatch(validated)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        raw = self.rfile.readline(MAX_WIRE + 2)
        if not raw.endswith(b"\n") or len(raw) > MAX_WIRE + 1:
            return
        request_signature = None
        try:
            parsed = json.loads(raw)
            if type(parsed) is dict and type(parsed.get("signature")) is str:
                signed = ({"envelope": parsed.get("envelope"),
                           "session_id": parsed.get("session_id")}
                          if self.server.bridge.sessions is not None
                          else parsed.get("envelope"))
                candidate = parsed["signature"]
                if len(candidate) == 64 and hmac.compare_digest(
                        sign(self.server.bridge.key, signed), candidate):
                    request_signature = candidate
        except (ValueError, UnicodeError, TypeError):
            pass
        try:
            result = self.server.bridge.process(raw.strip())
            response = {"ok": True, "result": result}
            if len(canonical(response)) > MAX_REPLY - 256:
                raise ValueError("response too large")
        except BridgeReadUnavailable as exc:
            response = {"ok": False, "error": "read_unavailable", "code": exc.code}
        except (InvalidBridgeRequest, ValueError, TypeError, KeyError):
            response = {"ok": False, "error": "request_rejected"}
        except Exception as exc:
            from .mcp_workspace_inspect import WorkspaceUnavailable
            if isinstance(exc, WorkspaceUnavailable):
                response = {"ok": False, "error": "read_unavailable", "code": exc.code}
            else:
                response = {"ok": False, "error": "bridge_unavailable"}
        if request_signature is not None and len(request_signature) == 64:
            response["reply_signature"] = sign_reply(
                self.server.bridge.key, request_signature, response)
        encoded = canonical(response)
        self.wfile.write(encoded + b"\n")


class BridgeUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """One owner per private socket directory; recover only proven stale sockets."""

    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, path, bridge):
        path = Path(path)
        parent = path.parent
        parent_info = parent.lstat()
        if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.geteuid():
            raise PermissionError("bridge directory must belong to service user")
        if parent_info.st_mode & 0o077:
            raise PermissionError("bridge directory must be private")
        self._path = path
        self._socket_identity = None
        self._lock_fd = None
        lock_path = parent / ".bridge.lock"
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        lock_fd = os.open(lock_path, flags, 0o600)
        try:
            lock_info = os.fstat(lock_fd)
            if (not stat.S_ISREG(lock_info.st_mode) or
                    lock_info.st_uid != os.geteuid() or
                    lock_info.st_mode & 0o077):
                raise PermissionError("unsafe bridge lock")
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise FileExistsError("another bridge owns the directory") from exc
            try:
                info = path.lstat()
            except FileNotFoundError:
                info = None
            if info is not None:
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                    raise PermissionError("unsafe existing bridge path")
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(1)
                    try:
                        probe.connect(str(path))
                    except OSError as exc:
                        if exc.errno != errno.ECONNREFUSED:
                            raise
                    else:
                        raise FileExistsError("bridge socket already active")
                # The exclusive lock prevents a second managed bridge from
                # racing us. Verify inode before removing the stale socket.
                current = path.lstat()
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                    raise FileExistsError("bridge path changed during recovery")
                path.unlink()
            super().__init__(str(path), _Handler)
            self.bridge = bridge
            os.chmod(path, 0o600)
            created = path.lstat()
            self._socket_identity = (created.st_dev, created.st_ino)
            self._lock_fd = lock_fd
        except BaseException:
            os.close(lock_fd)
            raise

    def server_close(self):
        try:
            super().server_close()
            if self._socket_identity is not None:
                try:
                    current = self._path.lstat()
                except FileNotFoundError:
                    pass
                else:
                    if (current.st_dev, current.st_ino) == self._socket_identity:
                        self._path.unlink()
                self._socket_identity = None
        finally:
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None


def call_unix(path, key, envelope, *, timeout=5, session_id=None, require_signed_reply=False):
    if session_id is None:
        payload = canonical({"envelope": envelope, "signature": sign(key, envelope)})
    else:
        signed = {"envelope": envelope, "session_id": session_id}
        payload = canonical({**signed, "signature": sign(key, signed)})
    if len(payload) > MAX_WIRE:
        raise ValueError("request too large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(path))
        sock.sendall(payload + b"\n")
        with sock.makefile("rb") as stream:
            reply = stream.readline(MAX_REPLY + 2)
    if not reply.endswith(b"\n") or len(reply) > MAX_REPLY + 1:
        raise ValueError("invalid bridge response")
    response = json.loads(reply)
    if type(response) is not dict:
        raise ValueError("invalid bridge response")
    if require_signed_reply:
        if set(response) not in ({"ok", "result", "reply_signature"},
                                 {"ok", "error", "reply_signature"},
                                 {"ok", "error", "code", "reply_signature"}):
            raise ValueError("invalid signed response")
        signature = response.get("reply_signature")
        body = {k: v for k, v in response.items() if k != "reply_signature"}
        expected = sign_reply(key, json.loads(payload)["signature"], body)
        if type(signature) is not str or not hmac.compare_digest(signature, expected):
            raise PermissionError("unauthenticated bridge response")
    if response.get("ok") is not True:
        if require_signed_reply and response.get("error") == "read_unavailable":
            raise BridgeReadUnavailable(response.get("code"))
        raise PermissionError("bridge request denied")
    return response["result"]
