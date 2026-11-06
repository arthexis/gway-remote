"""Bounded in-process Watchtower bridge session manager.

Session identifiers are server-issued and never derived from MCP arguments.
The manager holds no bearer token on disk. A trusted gateway must explicitly
register a verified session; sessions expire and are revalidated on each call.
"""
from __future__ import annotations

import secrets
import threading
import time

from .mcp_bridge_session import SessionBridgeDispatch


class BridgeSessions:
    def __init__(self, *, verifier, allowed_node, read_principal, execution=None,
                 inventory=None, max_sessions=128, lifetime=300):
        if not 1 <= max_sessions <= 1024 or not 1 <= lifetime <= 3600:
            raise ValueError("invalid session limits")
        self.verifier = verifier
        self.allowed_node = allowed_node
        self.read_principal = read_principal
        self.execution = execution
        self.inventory = inventory
        self.max_sessions = max_sessions
        self.lifetime = lifetime
        self.sessions = {}
        self.lock = threading.RLock()

    def register(self, *, token, audience):
        if not isinstance(token, str) or not token:
            raise PermissionError("missing trusted bearer")
        if self.allowed_node(token, audience) is not True:
            raise PermissionError("node denied")
        if not (self.verifier.verify(token, required_scope="gway:read")
                or self.verifier.verify(token, required_scope="gway:execute")):
            raise PermissionError("invalid bearer")
        with self.lock:
            now = time.monotonic()
            self.sessions = {key: value for key, value in self.sessions.items()
                             if value[0] > now}
            if len(self.sessions) >= self.max_sessions:
                raise PermissionError("session capacity exceeded")
            sid = secrets.token_hex(24)
            dispatch = SessionBridgeDispatch(
                verifier=self.verifier, session_token=token,
                allowed_node=self.allowed_node, read_principal=self.read_principal,
                execution=self.execution, inventory=self.inventory)
            self.sessions[sid] = (now + self.lifetime, audience, dispatch)
            return sid

    def revoke(self, session_id):
        with self.lock:
            self.sessions.pop(session_id, None)

    def dispatch(self, session_id, envelope):
        with self.lock:
            record = self.sessions.get(session_id)
            if record is None or record[0] <= time.monotonic():
                self.sessions.pop(session_id, None)
                raise PermissionError("session expired")
            _, audience, handler = record
        if envelope["audience"] != audience:
            raise PermissionError("session audience mismatch")
        return handler(envelope)
