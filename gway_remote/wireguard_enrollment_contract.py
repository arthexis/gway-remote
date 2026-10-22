"""WireGuard enrollment protocol validation; no network or peer side effects.

Only the dedicated Watchtower enrollment service may use this public contract.
Never include invitation tokens in URLs, headers, exception messages or logs.
"""
from __future__ import annotations

import base64
import binascii
import re

DEVICE = re.compile(r"^gway-[0-9]{3,}$")
TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
MAX_REQUEST_BYTES = 4096


class InvalidEnrollment(ValueError):
    """Safe generic error: do not interpolate untrusted or secret input."""


def validate_enrollment(body: object) -> tuple[str, str, str]:
    """Return (device, public_key, token), validating protocol fields.

    The public key is an X25519 WireGuard public key encoded as standard base64.
    Parsing a request must never consume its token or mutate peers.
    """
    if not isinstance(body, dict) or set(body) != {"device", "public_key", "token"}:
        raise InvalidEnrollment("invalid enrollment request")
    device, key, token = (body[k] for k in ("device", "public_key", "token"))
    if not isinstance(device, str) or not DEVICE.fullmatch(device):
        raise InvalidEnrollment("invalid enrollment request")
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise InvalidEnrollment("invalid enrollment request")
    if not isinstance(key, str) or len(key) != 44:
        raise InvalidEnrollment("invalid enrollment request")
    try:
        raw = base64.b64decode(key, validate=True)
    except (binascii.Error, ValueError):
        raise InvalidEnrollment("invalid enrollment request") from None
    if len(raw) != 32 or base64.b64encode(raw).decode("ascii") != key:
        raise InvalidEnrollment("invalid enrollment request")
    return device, key, token


def parse_enrollment_json(raw: bytes) -> tuple[str, str, str]:
    """Bound JSON parser input; no secrets included in errors."""
    import json

    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_REQUEST_BYTES:
        raise InvalidEnrollment("invalid enrollment request")
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        raise InvalidEnrollment("invalid enrollment request") from None
    return validate_enrollment(data)
