"""Fail-closed SSH host identity attestation contract for Watchtower enrollment.

This module is pure: it does not enroll, modify SSH configuration, or contact hosts.
The source of its trust is the authenticated restricted Watchtower snapshot channel.
"""
from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime, timezone

NODE = re.compile(r"gway-[0-9]{3,}$")
KEY_TYPE = "ssh-ed25519"


class HostIdentityError(ValueError):
    """Identity cannot be accepted for unattended inspection."""


def _stamp(value):
    if not isinstance(value, str):
        raise HostIdentityError("missing identity timestamp")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HostIdentityError("invalid identity timestamp") from exc
    if result.tzinfo is None:
        raise HostIdentityError("identity timestamp must be timezone-aware")
    return result.astimezone(timezone.utc)


def validate_public_key(value):
    if not isinstance(value, str):
        raise HostIdentityError("missing SSH public key")
    parts = value.split()
    if len(parts) != 2 or parts[0] != KEY_TYPE:
        raise HostIdentityError("SSH host key must be ED25519 without extra fields")
    try:
        raw = base64.b64decode(parts[1], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HostIdentityError("invalid SSH public key encoding") from exc
    # SSH wire encoding: uint32 length + type, uint32 length + 32-byte key.
    if len(raw) != 51 or raw[:4] != bytes((0,0,0,11)) or raw[4:15] != b"ssh-ed25519" or raw[15:19] != bytes((0,0,0,32)):
        raise HostIdentityError("invalid SSH ED25519 wire key")
    return f"{KEY_TYPE} {parts[1]}"


def validate_attestation(record, *, node, now=None):
    """Validate one active attestation already delivered by trusted Watchtower SSH.

    This cannot authenticate an untrusted JSON document on its own. Caller MUST
    authenticate the forced-command Watchtower transport before invoking it.
    """
    now = now or datetime.now(timezone.utc)
    if not isinstance(record, dict) or record.get("schema") != 1:
        raise HostIdentityError("unsupported host identity schema")
    if not NODE.fullmatch(node) or record.get("node") != node:
        raise HostIdentityError("host identity node mismatch")
    if record.get("state") != "active" or record.get("rotation_state") != "stable":
        raise HostIdentityError("host identity unavailable or rotating")
    binding = record.get("enrollment_binding")
    if not isinstance(binding, str) or not re.fullmatch(r"[a-f0-9]{64}", binding):
        raise HostIdentityError("invalid enrollment binding")
    wg = record.get("wireguard_identity")
    if not isinstance(wg, str) or not re.fullmatch(r"[a-zA-Z0-9+/]{43}=", wg):
        raise HostIdentityError("invalid WireGuard identity")
    try:
        if len(base64.b64decode(wg, validate=True)) != 32:
            raise ValueError()
    except (ValueError, binascii.Error) as exc:
        raise HostIdentityError("invalid WireGuard identity") from exc
    created = _stamp(record.get("created_at"))
    valid_until = _stamp(record.get("valid_until"))
    if created > now or valid_until <= now or valid_until <= created:
        raise HostIdentityError("inactive host identity period")
    key = validate_public_key(record.get("host_public_key"))
    return {"node": node, "host_key": key, "host_key_alias": f"gway-inspection-{node}",
            "enrollment_binding": binding, "wireguard_identity": wg}


def assert_pinned_identity(existing, attested):
    """Never trust a changed or absent pin via automatic TOFU.

    The initial pin must be installed through an authenticated, approved enrollment
    transition; this helper only accepts an identical previously trusted pin.
    """
    if existing is None:
        raise HostIdentityError("initial pin requires authenticated enrollment transition")
    if existing != attested["host_key"]:
        raise HostIdentityError("host key changed: explicit rotation required")
    return True
