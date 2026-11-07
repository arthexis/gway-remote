"""Fail-closed reconciliation of a pinned MCP source's live catalog.

This module prepares an operator-controlled policy update. It never writes
configuration, changes OAuth, or grants execution permission.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .mcp_source_policy import classify_source_catalog
from .mcp_source_registry import SourceRegistration
from .mcp_source_stdio import list_source_tools


def build_readonly_source_entry(registration, *, discover=list_source_tools):
    if not isinstance(registration, SourceRegistration) or not registration.enabled:
        raise ValueError("enabled source registration required")
    tools = classify_source_catalog(registration, discover(registration))
    return {
        "registration": {
            "source_id": registration.source_id,
            "revision": registration.revision,
            "executable": registration.executable,
            "argv": list(registration.argv),
            "run_as": registration.run_as,
            "enabled": registration.enabled,
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


def stage_policy(path, payload, digest):
    """Atomically stage a root-owned policy; never activate it automatically.

    Both hosts must independently verify the same digest before enabling
    GWAY_MCP_SOURCE_POLICY and GWAY_MCP_SOURCE_POLICY_SHA256.
    """
    if os.geteuid() != 0:
        raise PermissionError("root required to provision source policy")
    if type(path) is not str or not path.startswith("/etc/gway-mcp-gateway/"):
        raise ValueError("protected policy path required")
    if type(payload) is not bytes or len(payload) > 65536:
        raise ValueError("invalid policy bytes")
    if type(digest) is not str or hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("source policy digest mismatch")
    target = Path(path)
    parent = target.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ValueError("untrusted policy directory")
    parent_stat = parent.stat()
    if parent_stat.st_uid != 0 or parent_stat.st_mode & 0o022:
        raise ValueError("policy directory must be root-owned and protected")
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError("untrusted existing policy")
    if target.exists() and (target.stat().st_uid != 0 or target.stat().st_mode & 0o022):
        raise ValueError("untrusted existing policy permissions")
    fd, temporary = tempfile.mkstemp(prefix=".mcp-source-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return digest
