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


def reconcile_sources(registrations, *, discover=list_source_tools):
    """Discover every registered source independently, never widening permissions.

    A failed source is withheld from the candidate catalog and reported.
    The returned payload is only a staging candidate: operator approval,
    digest pinning and gateway activation are separate required steps.
    """
    if type(registrations) not in (tuple, list) or len(registrations) > 16:
        raise ValueError("invalid registrations")
    ids = set()
    entries, failures, execution_required = [], {}, {}
    for registration in registrations:
        if not isinstance(registration, SourceRegistration):
            raise ValueError("invalid registration")
        if registration.source_id in ids:
            raise ValueError("duplicate source")
        ids.add(registration.source_id)
        if not registration.enabled:
            continue
        try:
            entry, pending = build_readonly_source_entry(
                registration, discover=discover)
        except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
            failures[registration.source_id] = type(exc).__name__
            continue
        entries.append(entry)
        execution_required[registration.source_id] = pending
    payload, digest = policy_payload(entries)
    return {
        "policy": payload,
        "sha256": digest,
        "failures": failures,
        "execute_required": execution_required,
    }
