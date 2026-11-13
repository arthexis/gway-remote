"""Pure, offline FederatedAuthContextV1 codec; NOT an authorization service.

Callers MUST obtain verified_principal from a trusted verifier (for example,
BearerVerifier.execution_principal) and MUST separately authenticate the SSH
transport, its peer, and node-owned policy. Neither this JSON-shaped context nor
its SHA-256 digest attests identity, confers a permission, prevents replay, or
protects an Odoo writer against direct invocation. No runtime imports this module.
"""

import hashlib
import json
import math
import re


VERSION = 1
MAX_ARGUMENT_BYTES = 32768
MAX_NESTING = 24
FIELDS = frozenset({
    "version", "principal_id", "scope", "node", "provider", "tool",
    "request_id", "arguments_sha256",
})
_HEX_PRINCIPAL = re.compile(r"[0-9a-f]{24}\Z")
_HEX_REQUEST = re.compile(r"[0-9a-f]{32}\Z")
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_NODE = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")
_PROVIDER = re.compile(r"[a-z][a-z0-9_]{1,39}\Z")
_TOOL = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_MAX_SAFE_INT = (1 << 53) - 1


class AuthContextError(ValueError):
    """Stable sanitized rejection; never emit identities or payload data."""

    def __init__(self):
        super().__init__("invalid_federated_auth_context_v1")


def _valid_text(value, pattern):
    return type(value) is str and pattern.fullmatch(value) is not None


def _check_json_value(value, *, depth=0, active=None):
    """Reject non-JSON objects, cycles, excessive depth, and unsafe numbers."""
    if depth > MAX_NESTING:
        raise AuthContextError()
    if value is None or type(value) is bool:
        return
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise AuthContextError() from None
        return
    if type(value) is int:
        if abs(value) > _MAX_SAFE_INT:
            raise AuthContextError()
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise AuthContextError()
        return
    if type(value) not in (dict, list):
        raise AuthContextError()
    if active is None:
        active = set()
    if id(value) in active:
        raise AuthContextError()
    active.add(id(value))
    try:
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise AuthContextError()
                _check_json_value(key, depth=depth + 1, active=active)
                _check_json_value(item, depth=depth + 1, active=active)
        else:
            for item in value:
                _check_json_value(item, depth=depth + 1, active=active)
    finally:
        active.remove(id(value))


def canonical_arguments(arguments):
    """V1 JSON bytes: sorted keys, compact separators, UTF-8, finite numbers.

    This is a versioned Python JSON convention, NOT RFC 8785/JCS. Numeric type
    changes (e.g. 1 vs 1.0) deliberately change the digest. The digest binds
    bytes but provides neither authenticity nor idempotency.
    """
    if type(arguments) is not dict:
        raise AuthContextError()
    _check_json_value(arguments)
    try:
        raw = json.dumps(arguments, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise AuthContextError() from None
    if len(raw) > MAX_ARGUMENT_BYTES:
        raise AuthContextError()
    return raw


def arguments_sha256(arguments):
    return hashlib.sha256(canonical_arguments(arguments)).hexdigest()


def _check_binding(*, principal_id, node, provider, tool, request_id):
    if not (_valid_text(principal_id, _HEX_PRINCIPAL)
            and _valid_text(node, _NODE)
            and _valid_text(provider, _PROVIDER)
            and _valid_text(tool, _TOOL)
            and _valid_text(request_id, _HEX_REQUEST)):
        raise AuthContextError()


def build_context(*, verified_principal, node, provider, tool, request_id, arguments):
    """Construct from a caller-supplied already verified stable principal.

    This pure helper cannot inspect a bearer and must never receive user MCP
    arguments as the source of the verified principal or routing fields.
    """
    _check_binding(principal_id=verified_principal, node=node, provider=provider,
                   tool=tool, request_id=request_id)
    return {
        "version": VERSION,
        "principal_id": verified_principal,
        "scope": "execute",
        "node": node,
        "provider": provider,
        "tool": tool,
        "request_id": request_id,
        "arguments_sha256": arguments_sha256(arguments),
    }


def validate_context(context, *, verified_principal, node, provider, tool,
                     request_id, arguments):
    """Match a V1 context against independently trusted peer/routing inputs.

    The caller must authenticate the origin and supply verified_principal
    independently of the context itself. Passing context['principal_id'] as
    verified_principal would defeat the principal-binding check.
    """
    if type(context) is not dict or set(context) != FIELDS:
        raise AuthContextError()
    _check_binding(principal_id=verified_principal, node=node, provider=provider,
                   tool=tool, request_id=request_id)
    if (type(context["version"]) is not int or context["version"] != VERSION
            or context["scope"] != "execute" or type(context["scope"]) is not str
            or context["principal_id"] != verified_principal
            or context["node"] != node or context["provider"] != provider
            or context["tool"] != tool or context["request_id"] != request_id
            or not _valid_text(context["arguments_sha256"], _HEX_DIGEST)
            or context["arguments_sha256"] != arguments_sha256(arguments)):
        raise AuthContextError()
    # Copy, so changes to the caller's dictionary cannot change the result.
    return dict(context)
