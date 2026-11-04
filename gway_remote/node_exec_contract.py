"""M3 B1: pure, non-executing shell-job contract.

A preview is informational, not approval or a dispatch capability. This module
imports no SSH, subprocess, os.system or execution service and makes no writes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets

SCHEMA_VERSION = 1
MAX_COMMAND_BYTES = 4096
PREVIEW_TTL_SECONDS = 60
WAIT_SECONDS = 10
MAX_OUTPUT_CHUNK = 16384
DEFAULT_LIMITS = {
    "wait_seconds": WAIT_SECONDS,
    "job_timeout_seconds": 60,
    "max_output_bytes": 1048576,
    "max_output_chunk_bytes": MAX_OUTPUT_CHUNK,
    "memory_max_bytes": 134217728,
    "tasks_max": 32,
    "concurrent_jobs_per_node": 1,
}
STATES = frozenset({"queued", "running", "succeeded", "failed", "cancelled", "timed_out", "unknown"})
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out", "unknown"})
TRANSITIONS = {
    "queued": frozenset({"running", "cancelled", "timed_out", "unknown"}),
    "running": frozenset({"succeeded", "failed", "cancelled", "timed_out", "unknown"}),
}
_NODE = re.compile(r"gway-[0-9]{3,}$")
_REQUEST = re.compile(r"[a-f0-9]{32}$")


def command_digest(node: str, command: str, identity: str) -> str:
    """Unambiguous digest of request data, not a grant of permission."""
    encoded = json.dumps([SCHEMA_VERSION, node, command, identity],
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_command(node, command):
    if type(node) is not str or not _NODE.fullmatch(node):
        raise ValueError("invalid node")
    if type(command) is not str or not command.strip() or "\x00" in command:
        raise ValueError("invalid shell command")
    if len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
        raise ValueError("shell command exceeds size bound")
    return command


def preview(node, command, inventory):
    """Check an already authenticated Watchtower view; never resolve a client IP."""
    validate_command(node, command)
    if type(inventory) is not dict or type(inventory.get("nodes")) is not list:
        raise ValueError("node inventory unavailable")
    matches = [row for row in inventory["nodes"]
               if type(row) is dict and row.get("node") == node]
    if len(matches) != 1:
        raise ValueError("node is not enrolled")
    row = matches[0]
    if (row.get("registered") is not True or row.get("identity_verified") is not True
            or type(row.get("execute_available")) is not bool):
        raise ValueError("node identity or execution gate unavailable")
    # A preview is information, not a dispatch permit.
    # Its nonce must never be used as an execution request ID.
    now = datetime.now(timezone.utc)
    return {
        "schema": SCHEMA_VERSION,
        "node": node,
        "shell": "/bin/sh",
        "command": command,
        "command_sha256": command_digest(node, command, row["node"]),
        "preview_id": secrets.token_hex(16),
        "expires_at": (now + timedelta(seconds=PREVIEW_TTL_SECONDS)).isoformat(),
        "limits": dict(DEFAULT_LIMITS),
        "authorization": {"required_scope": "gway:execute",
                          "approval_required": False},
        "status": "preview_only",
        "execute_available": bool(row.get("execute_eligible", False) and row.get("reachable") == "reachable"),
    }


def validate_transition(previous, next_state):
    if previous not in STATES or next_state not in STATES:
        raise ValueError("invalid job state")
    if next_state not in TRANSITIONS.get(previous, frozenset()):
        raise ValueError("invalid job state transition")
    return next_state


def validate_result(result):
    """Validate a versioned job result shape; does not persist or execute jobs."""
    if type(result) is not dict or result.get("schema") != SCHEMA_VERSION:
        raise ValueError("invalid job result")
    if type(result.get("request_id")) is not str or not _REQUEST.fullmatch(result["request_id"]):
        raise ValueError("invalid request ID")
    if type(result.get("node")) is not str or not _NODE.fullmatch(result["node"]):
        raise ValueError("invalid result node")
    if result.get("status") not in STATES:
        raise ValueError("invalid result status")
    if type(result.get("stdout")) is not str or type(result.get("stderr")) is not str:
        raise ValueError("invalid result output")
    if len(result["stdout"].encode("utf-8")) + len(result["stderr"].encode("utf-8")) > MAX_OUTPUT_CHUNK:
        raise ValueError("output chunk exceeds bound")
    if type(result.get("truncated")) is not bool:
        raise ValueError("missing truncation marker")
    if type(result.get("cursor")) not in (str, type(None)):
        raise ValueError("invalid output cursor")
    if result.get("exit_code") is not None and type(result["exit_code"]) is not int:
        raise ValueError("invalid exit code")
    if result["status"] not in TERMINAL and result["exit_code"] is not None:
        raise ValueError("running job cannot have exit code")
    for key in ("started_at", "finished_at"):
        stamp = result.get(key)
        if stamp is not None:
            try:
                dt = datetime.fromisoformat(stamp)
                if dt.tzinfo is None:
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError("invalid result timestamp") from None
    return result
