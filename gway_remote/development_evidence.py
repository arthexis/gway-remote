"""Read-only evidence projection for existing Appliance Deploy attempts.

This module neither reads the host nor invokes GitHub, MCP, Ansible or installers.
The original attempt journal remains authoritative for what it *records*, not
for the independently verified installed release or service health.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

from .reconcile import TARGETS

_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
_ALLOWED = frozenset(name for name, _ in TARGETS)
_ATTEMPT = frozenset({"started", "installed", "staged", "failed"})
_CI = frozenset({"success", "failure", "pending", "unknown"})


def _sha(value):
    return value.lower() if isinstance(value, str) and _SHA.fullmatch(value) else None


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def deployment_receipt(name, attempt, *, observed_sha=None, health=None):
    """Normalize one existing attempt without promoting journal claims to proof.

    observed_sha must come from an independent read-only installed-release
    probe. None is *unknown*, not evidence of an absent installation.
    """
    if name not in _ALLOWED:
        raise ValueError("unrecognized deployment target")
    if not isinstance(attempt, dict):
        raise ValueError("invalid attempt entry")
    sha = _sha(attempt.get("sha"))
    status = attempt.get("status")
    at = _time(attempt.get("at"))
    if sha is None or status not in _ATTEMPT or at is None:
        raise ValueError("invalid attempt evidence")
    if observed_sha is not None and _sha(observed_sha) is None:
        raise ValueError("invalid observed revision")
    if health not in (None, "healthy", "unhealthy", "unknown"):
        raise ValueError("invalid health observation")
    observed = _sha(observed_sha)
    release = ("matching" if observed == sha else "different") if observed else "unknown"
    # The journal's 'installed' status is an installer outcome, not runtime proof.
    acceptance = ("verified" if status == "installed" and release == "matching"
                  and health == "healthy" else "unknown")
    return {
        "schema": "gway.deployment-receipt.v1",
        "target": name,
        "repository": dict(TARGETS)[name],
        "requested_sha": sha,
        "attempt_status": status,
        "attempt_at": at,
        "installed_sha": observed,
        "release_match": release,
        "health": health or "unknown",
        "acceptance": acceptance,
    }


def development_snapshot(*, receipt=None, github_head=None, ci="unknown",
                         blocked_reason=None):
    """Pure read-only projection; does not authorize a deploy or change state."""
    head = _sha(github_head) if github_head is not None else None
    if github_head is not None and head is None:
        raise ValueError("invalid GitHub head")
    if ci not in _CI:
        raise ValueError("invalid CI status")
    if receipt is not None and (
        not isinstance(receipt, dict) or
        receipt.get("schema") != "gway.deployment-receipt.v1"
    ):
        raise ValueError("invalid receipt")
    if blocked_reason is not None and (not isinstance(blocked_reason, str)
                                       or not blocked_reason.strip()):
        raise ValueError("invalid blocker")
    installed = receipt.get("installed_sha") if receipt else None
    if blocked_reason:
        stage, reason = "blocked", blocked_reason
    elif head is None or ci == "unknown":
        stage, reason = "unknown", "GitHub revision or CI evidence unavailable"
    elif ci != "success":
        stage, reason = "blocked", "CI not successful"
    elif receipt is None or installed is None:
        stage, reason = "unknown", "independent installed release unavailable"
    elif installed != head:
        stage, reason = "pending", "installed revision differs from GitHub HEAD"
    elif receipt["acceptance"] != "verified":
        stage, reason = "pending", "functional or health acceptance unverified"
    else:
        stage, reason = "accepted", "matching release and health evidence supplied"
    return {"schema": "gway.development-snapshot.v1", "stage": stage,
            "reason": reason, "github_head": head, "ci": ci, "receipt": receipt}
