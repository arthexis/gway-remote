"""Authenticated Unix-socket transport for the private Watchtower bridge.

This is intentionally local to Watchtower. Remote node access must be carried
through the separately authenticated and authorized node relay, never by
exposing this Unix socket over an unauthenticated TCP listener.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import socketserver
import threading
import time
from pathlib import Path

from .mcp_bridge_contract import InvalidBridgeRequest, validate_envelope

MAX_WIRE = 16384
MAX_REPLY = 16384


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sign(key, envelope):
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("bridge key must contain at least 32 bytes")
    return hmac.new(key, canonical(envelope), hashlib.sha256).hexdigest()


class AuthenticatedBridge:
    def __init__(self, key, *, audience, dispatch):
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("weak bridge key")
        self.key = key
        self.audience = audience
        self.dispatch = dispatch
        self.seen = {}
        self.lock = threading.Lock()

    def process(self, raw, *, now=None):
        if not isinstance(raw, bytes) or len(raw) > MAX_WIRE:
            raise InvalidBridgeRequest("invalid wire size")
        try:
            request = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise InvalidBridgeRequest("invalid JSON") from exc
        if type(request) is not dict or set(request) != {"envelope", "signature"}:
            raise InvalidBridgeRequest("invalid signed request")
        envelope, signature = request["envelope"], request["signature"]
        if type(signature) is not str or len(signature) != 64:
            raise InvalidBridgeRequest("invalid signature")
        if not hmac.compare_digest(sign(self.key, envelope), signature):
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
        return self.dispatch(validated)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        raw = self.rfile.readline(MAX_WIRE + 2)
        if not raw.endswith(b"\\n") or len(raw) > MAX_WIRE + 1:
            return
        try:
            result = self.server.bridge.process(raw.strip())
            response = {"ok": True, "result": result}
            encoded = canonical(response)
            if len(encoded) > MAX_REPLY:
                raise ValueError("response too large")
        except (InvalidBridgeRequest, ValueError, TypeError, KeyError):
            encoded = b'{"ok":false,"error":"request_rejected"}'
        except Exception:
            encoded = b'{"ok":false,"error":"bridge_unavailable"}'
        self.wfile.write(encoded + b"\\n")


class BridgeUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, path, bridge):
        path = Path(path)
        if path.exists() or path.is_symlink():
            raise FileExistsError("bridge socket path already exists")
        super().__init__(str(path), _Handler)
        self.bridge = bridge
        os.chmod(path, 0o600)


def call_unix(path, key, envelope, *, timeout=5):
    payload = canonical({"envelope": envelope, "signature": sign(key, envelope)})
    if len(payload) > MAX_WIRE:
        raise ValueError("request too large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(path))
        sock.sendall(payload + b"\\n")
        with sock.makefile("rb") as stream:
            reply = stream.readline(MAX_REPLY + 2)
    if not reply.endswith(b"\\n") or len(reply) > MAX_REPLY + 1:
        raise ValueError("invalid bridge response")
    response = json.loads(reply)
    if type(response) is not dict or response.get("ok") is not True:
        raise PermissionError("bridge request denied")
    return response["result"]
