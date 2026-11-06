"""Fail-closed reconciliation of a pinned MCP source's live catalog.

This module prepares an operator-controlled policy update. It never writes
configuration, changes OAuth, or grants execution permission.
"""
import hashlib
import json

from .mcp_source_policy import classify_source_catalog
from .mcp_source_registry import SourceRegistration
from .mcp_source_stdio import list_source_tools


def build_readonly_source_entry(registration, *, discover=list_source_tools):
    if not isinstance(registration, SourceRegistration) or not registration.enabled:
        raise ValueError("enabled source registration required")
    if registration.permission != "read":
        raise ValueError("execute sources are not supported")
    tools = classify_source_catalog(registration, discover(registration))
    return {
        "registration": {
            "source_id": registration.source_id,
            "revision": registration.revision,
            "executable": registration.executable,
            "argv": list(registration.argv),
            "run_as": registration.run_as,
            "enabled": registration.enabled,
            "permission": registration.permission,
        },
        "tools": tools["read"],
    }, tuple(tool["name"] for tool in tools["execute_required"])


def policy_payload(entries):
    """Produce canonical identical bytes/digest for independent host staging."""
    if type(entries) not in (list, tuple) or len(entries) > 16:
        raise ValueError("invalid entries")
    ids = [entry["registration"]["source_id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate source")
    payload = json.dumps(
        {"version": 1, "sources": sorted(entries, key=lambda e: e["registration"]["source_id"])},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    if len(payload) > 65536:
        raise ValueError("policy too large")
    return payload, hashlib.sha256(payload).hexdigest()
