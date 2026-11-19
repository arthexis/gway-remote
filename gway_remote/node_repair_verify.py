"""Repair-first operational acceptance using existing Watchtower authorization.

No private transport or identity can be selected by the caller. Read-only
limits uses the already pinned SSH route; an optional terminal test must pass
the current authenticated execute principal through AuthorizedExecution,
which owns both durable dispatch and result correlation.
"""
from __future__ import annotations

import secrets
import subprocess

from .watchtower_exec_transport import SSHTransportFailure, pinned_transport

_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out", "unknown"})


def failure_category(exc):
    """Stable, secret-free stage class for post-failure investigation."""
    if isinstance(exc, SSHTransportFailure):
        return "ssh_transport"
    if isinstance(exc, PermissionError):
        return "authorization_or_pin"
    if isinstance(exc, (subprocess.SubprocessError, OSError)):
        return "ssh_transport"
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "node_protocol"
    return "unavailable"


def verify_limits(authorized, node, *, request_id_factory=None):
    """One read-only strict-pinned SSH probe, not an identity preflight.

    Current eligibility is checked by the existing execution authority.
    An accepted limits response proves a live SSH protocol, not worker health.
    """
    try:
        authorized._allow_preview_eligibility(node)
        transport = pinned_transport(authorized.relay.transport, node)
        rid = request_id_factory() if request_id_factory is not None else secrets.token_hex(16)
        response = transport.invoke({"operation": "limits", "node": node, "request_id": rid})
        if (type(response) is not dict or response.get("node") != node
                or response.get("request_id") != rid
                or type(response.get("concurrent_jobs_per_node")) is not int
                or not 1 <= response["concurrent_jobs_per_node"] <= 8):
            return {"schema": 1, "node": node, "stage": "limits",
                    "status": "failed", "category": "node_protocol"}
        return {"schema": 1, "node": node, "stage": "limits",
                "status": "succeeded", "concurrent_jobs_per_node": response["concurrent_jobs_per_node"]}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, RuntimeError, PermissionError) as exc:
        return {"schema": 1, "node": node, "stage": "limits",
                "status": "failed", "category": failure_category(exc)}


def verify_terminal(authorized, *, principal, node, request_id_factory=None):
    """Explicit execute-authorized one-shot hostname smoke test.

    Existing Watchtower authorization and ledger govern submit/status.
    Incomplete/uncertain operations are never submitted again by this function.
    """
    rid = request_id_factory() if request_id_factory is not None else secrets.token_hex(16)
    try:
        result = authorized.exec(principal=principal, request_id=rid, node=node,
                                 command="hostname", wait_seconds=10)
        if (type(result) is not dict or result.get("node") != node
                or result.get("request_id") != rid):
            return {"schema": 1, "node": node, "stage": "terminal",
                    "status": "uncertain", "category": "uncorrelated_result"}
        if result.get("status") not in _TERMINAL:
            result = authorized.result(principal=principal, request_id=rid)
        if (type(result) is not dict or result.get("node") != node
                or result.get("request_id") != rid):
            return {"schema": 1, "node": node, "stage": "terminal",
                    "status": "uncertain", "category": "uncorrelated_result"}
        if result.get("status") == "succeeded":
            if (result.get("stdout") == node + "\n" and
                    result.get("exit_code") == 0):
                return {"schema": 1, "node": node, "stage": "terminal", "status": "succeeded"}
            return {"schema": 1, "node": node, "stage": "terminal",
                    "status": "failed", "category": "unexpected_host_result"}
        state = result.get("status")
        return {"schema": 1, "node": node, "stage": "terminal",
                "status": "uncertain" if state not in _TERMINAL else "failed",
                "category": result.get("failure_stage")
                if result.get("failure_stage") in {"ssh_transport", "worker_readiness"}
                else ("terminal_" + state if state in _TERMINAL else "terminal_pending")}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, PermissionError) as exc:
        # A submit may have reached the node; do not resubmit this request ID.
        return {"schema": 1, "node": node, "stage": "terminal",
                "status": "uncertain", "category": failure_category(exc)}
