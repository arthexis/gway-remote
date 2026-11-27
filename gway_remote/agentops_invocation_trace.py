"""Sanitized correlation of authenticated AgentOps MCP ingress and node RPC.

This is observation only: never use correlation data as authorization.
The server-generated ID is propagated in the existing authenticated SSH
envelope and provider JSON-RPC ID, not in caller-controlled arguments.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
import sys

_ACTIVE = ContextVar("agentops_ingress_trace", default=None)
_ID = re.compile(r"[0-9a-f]{32}\Z")
_PRINCIPAL = re.compile(r"[0-9a-f]{24}\Z")


def valid_id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def current_id():
    return _ACTIVE.get()


def event(stage, trace_id, **fields):
    if stage not in ("ingress", "transport", "returned", "uncertain") or not valid_id(trace_id):
        raise ValueError("invalid_agentops_trace")
    data = {"schema": "agentops-mcp-trace/v1", "stage": stage,
            "trace_id": trace_id, "observed_at": datetime.now(timezone.utc).isoformat()}
    for key, value in fields.items():
        if key == "principal" and type(value) is str and _PRINCIPAL.fullmatch(value):
            data[key] = value
        elif key == "client_rpc_id_sha256" and type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value):
            data[key] = value
        elif key == "scope" and value in ("read", "execute"):
            data[key] = value
        elif key in ("node", "tool") and type(value) is str and re.fullmatch(r"[a-z][a-z0-9_-]{0,127}", value):
            data[key] = value
    print(json.dumps(data, separators=(",", ":")), file=sys.stderr, flush=True)


@contextmanager
def ingress(provider, *, registry, credential, scope, rpc_id):
    if provider != "agentops":
        yield
        return
    rid = secrets.token_hex(16)
    # The existing verifier supplies a pseudonymous principal. No token,
    # user-supplied identity, session contents or raw RPC ID is retained.
    try:
        from .mcp_principal_admission import verify_admission
        principal = verify_admission(registry, credential, scope)
    except (AttributeError, PermissionError, ValueError, RuntimeError, OSError, TypeError):
        principal = None
    digest = hashlib.sha256(json.dumps(rpc_id, ensure_ascii=True,
                            separators=(",", ":")).encode()).hexdigest()
    token = _ACTIVE.set(rid)
    try:
        event("ingress", rid, principal=principal, scope=scope,
              client_rpc_id_sha256=digest)
        yield
    finally:
        _ACTIVE.reset(token)
