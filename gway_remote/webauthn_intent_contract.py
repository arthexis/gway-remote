"""Pure Stage B request-binding contract for future Watchtower WebAuthn issuer.

This module is not an authenticator, an HTTP API or a token issuer. It contains
only strict, serializable, public action parameters to bind into a challenge.
Only Stage C's verified one-shot authority may act on its return value.
"""
import hashlib
import json
import re

MCP_SCOPES = ("gway:execute", "gway:read")
MAX_LIFETIME_SECONDS = 30 * 86400
DEFAULT_LIFETIME_SECONDS = 86400
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX24 = re.compile(r"[0-9a-f]{24}\Z")


def canonical_admin_intent(value):
    """Return allowlisted, canonical JSON bytes or reject an untrusted intent.

    No filesystem paths, credentials, host selectors, or secret values are accepted.
    Request idempotency is explicitly distinct from a WebAuthn challenge handle.
    """
    if type(value) is not dict or type(value.get("action")) is not str:
        raise ValueError("invalid_admin_intent")
    action = value["action"]
    if action == "issue_mcp_bearer":
        if set(value) != {"action", "scopes", "lifetime_seconds", "request_id"}:
            raise ValueError("invalid_admin_intent")
        scopes = value["scopes"]
        lifetime = value["lifetime_seconds"]
        if (type(scopes) is not list or len(scopes) != len(MCP_SCOPES)
                or any(type(scope) is not str for scope in scopes)
                or sorted(scopes) != list(MCP_SCOPES)
                or type(lifetime) is not int
                or not 60 <= lifetime <= MAX_LIFETIME_SECONDS):
            raise ValueError("invalid_admin_intent")
        canonical = {"action": action, "scopes": list(MCP_SCOPES),
                     "lifetime_seconds": lifetime, "request_id": value["request_id"]}
    elif action == "revoke_mcp_bearer":
        if set(value) != {"action", "key_id", "request_id"}:
            raise ValueError("invalid_admin_intent")
        key_id = value["key_id"]
        if type(key_id) is not str or not _HEX24.fullmatch(key_id):
            raise ValueError("invalid_admin_intent")
        canonical = {"action": action, "key_id": key_id,
                     "request_id": value["request_id"]}
    else:
        # Secret reveal/update require an independently reviewed #381 policy.
        raise ValueError("invalid_admin_intent")
    request_id = value["request_id"]
    if type(request_id) is not str or not _HEX32.fullmatch(request_id):
        raise ValueError("invalid_admin_intent")
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")


def admin_intent_digest(value):
    """Digest to store with a one-use assertion challenge in Stage C."""
    return hashlib.sha256(canonical_admin_intent(value)).digest()
