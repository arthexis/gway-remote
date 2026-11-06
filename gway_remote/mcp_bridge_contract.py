"""Strict validation for the node-to-Watchtower infrastructure RPC envelope.

This module defines a transport-independent boundary. Authentication and replay
storage are mandatory at the eventual transport, not implied by this validator.
"""
from __future__ import annotations

import re
import time

VERSION = 1
MAX_TTL = 60
MAX_CLOCK_SKEW = 5
NODE = re.compile(r"gway-[0-9]{3}", re.ASCII)
REQUEST = re.compile(r"[0-9a-f]{32}", re.ASCII)
OPERATIONS = frozenset({
    "inventory.list", "inventory.capabilities", "execution.preview",
    "execution.start", "execution.result", "execution.cancel",
    "deployment.preview", "deployment.start", "deployment.status",
})
EXECUTE_OPERATIONS = frozenset({
    "execution.start", "execution.result", "execution.cancel",
    "deployment.start", "deployment.status",
})


class InvalidBridgeRequest(ValueError):
    pass


def validate_envelope(data, *, audience, now=None):
    """Validate a bounded internal request; never treat this as authentication."""
    if type(data) is not dict or set(data) != {
        "version", "request_id", "principal", "audience", "operation",
        "scope", "issued_at", "expires_at", "arguments"
    }:
        raise InvalidBridgeRequest("invalid envelope fields")
    if type(data["version"]) is not int or data["version"] != VERSION:
        raise InvalidBridgeRequest("unsupported envelope version")
    if type(data["request_id"]) is not str or not REQUEST.fullmatch(data["request_id"]):
        raise InvalidBridgeRequest("invalid request ID")
    if type(data["principal"]) is not str or not 1 <= len(data["principal"]) <= 128:
        raise InvalidBridgeRequest("invalid principal")
    if type(audience) is not str or not NODE.fullmatch(audience) or data["audience"] != audience:
        raise InvalidBridgeRequest("wrong audience")
    operation = data["operation"]
    if type(operation) is not str or operation not in OPERATIONS:
        raise InvalidBridgeRequest("operation not allowed")
    scope = data["scope"]
    if scope not in ("gway:read", "gway:execute"):
        raise InvalidBridgeRequest("invalid scope")
    if operation in EXECUTE_OPERATIONS and scope != "gway:execute":
        raise InvalidBridgeRequest("insufficient scope")
    issued, expires = data["issued_at"], data["expires_at"]
    if type(issued) is not int or type(expires) is not int:
        raise InvalidBridgeRequest("invalid timestamps")
    current = int(time.time()) if now is None else now
    if not issued - MAX_CLOCK_SKEW <= current < expires or not 0 < expires - issued <= MAX_TTL:
        raise InvalidBridgeRequest("expired or future request")
    args = data["arguments"]
    if type(args) is not dict or len(args) > 16:
        raise InvalidBridgeRequest("invalid arguments")
    if len(str(args).encode("utf-8")) > 8192:
        raise InvalidBridgeRequest("arguments too large")
    return data
