"""Conservative, read-only v1 evidence adapter for legacy status rows.

This adapter does not perform I/O. Existing status API fields remain unchanged.
"""
from __future__ import annotations

from datetime import datetime
import re

from .probe_registry import probe_for
from .reconcile import TARGETS

_SCHEMA = 1


def adapt_component(row: dict, *, observed_at: str | None, depth: str = "deep",
                    kiosk_activation_verified: bool = False) -> dict:
    name = row["name"]
    spec = probe_for(name)
    bastion = name == "gway-bastion"
    staged = row.get("staged_sha") if bastion else None
    installed = row.get("installed_sha")
    release_state = row.get("release_state") if bastion else None
    # A revision file alone does not establish activation.
    kiosk_verified = (name == "gway-ap-kiosk" and depth == "deep"
                      and kiosk_activation_verified is True
                      and isinstance(installed, str)
                      and re.fullmatch(r"[0-9a-f]{40}", installed) is not None)
    activation_verified = bool(installed) and (bastion and release_state == "activated"
                                                or kiosk_verified
                                                or not bastion and not spec.revision_file)
    if bastion and release_state == "staged" and staged and not installed:
        installation = "staged"
    elif activation_verified:
        installation = "activated"
    else:
        installation = "unknown"
    # AgentOps is an on-demand CLI: --help probes installation, not a daemon.
    # Reports also has an executable, but its role/warehouse readiness is required.
    runtime_required = name != "gway-agent-ops"
    runtime = row.get("health", "unknown")
    if depth != "deep" and not bastion:
        runtime = "unknown"
    if runtime not in ("healthy", "unhealthy", "unknown", "not_applicable"):
        runtime = "unknown"
    if not runtime_required:
        # A valid active release has no continuously running service to inspect.
        runtime = "not_applicable" if activation_verified else "unknown"
    elif runtime == "not_applicable":
        runtime = "unknown"
    # Staged-only Bastion has no activated runtime to check. Do not infer that an
    # activated Bastion is healthy from the release record.
    if bastion:
        runtime = "not_applicable" if installation == "staged" else "unknown"
    evidence = []
    if staged:
        evidence.append("verified_staged_release")
    if activation_verified:
        evidence.append("verified_active_release")
    if row.get("evidence") == "invalid":
        evidence.append("invalid_release_evidence")
    return {
        "schema_version": _SCHEMA,
        "repository": dict(TARGETS).get(name),
        "source_revision": None,  # Attempted SHA is not verified source evidence.
        "staged_revision": staged,
        "activated_revision": installed if activation_verified else None,
        "activated_at": row.get("activated_at") if activation_verified else None,
        "installation_state": installation,
        "runtime_state": runtime,
        "observed_at": observed_at if depth == "deep" else None,
        "evidence": evidence,
        "errors": ["invalid_release_evidence"] if row.get("evidence") == "invalid" else [],
        "capabilities": {
            "staging": bastion,
            "activation": True,
            "runtime_probe": runtime_required and not bastion and spec.kind != "unknown",
            "runtime_required": runtime_required,
        },
    }



# One v1 schema: adapt_component's existing public envelope is authoritative.
# Attempt metadata is deliberately not mixed with verified release evidence.
RECOVERY_ROLLBACK = frozenset(("gway-remote", "ocpp-csms"))
_SHA = re.compile(r"^[a-fA-F0-9]{7,40}$")


def recovery_strategy(component: str) -> str:
    if not isinstance(component, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", component):
        raise ValueError("invalid component")
    return "rollback" if component in RECOVERY_ROLLBACK else "fail_forward"


def _revision(value):
    if value is not None and (not isinstance(value, str) or not _SHA.fullmatch(value)):
        raise ValueError("invalid revision")
    return value


def _timestamp(value):
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError("invalid timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")


def validate(record: dict) -> dict:
    """Validate the existing v1 envelope without altering its public shape."""
    keys = {"schema_version", "repository", "source_revision", "staged_revision",
            "activated_revision", "activated_at", "installation_state", "runtime_state",
            "observed_at", "evidence", "errors", "capabilities"}
    if not isinstance(record, dict) or set(record) != keys or record["schema_version"] != 1:
        raise ValueError("invalid evidence schema")
    if record["repository"] is not None and (
            not isinstance(record["repository"], str) or
            not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", record["repository"])):
        raise ValueError("invalid repository")
    for key in ("source_revision", "staged_revision", "activated_revision"):
        _revision(record[key])
    for key in ("activated_at", "observed_at"):
        _timestamp(record[key])
    if record["installation_state"] not in ("staged", "activated", "unknown"):
        raise ValueError("invalid installation state")
    if record["runtime_state"] not in ("healthy", "unhealthy", "unknown", "not_applicable"):
        raise ValueError("invalid runtime state")
    if not isinstance(record["evidence"], list) or not all(isinstance(v, str) for v in record["evidence"]):
        raise ValueError("invalid evidence list")
    if not isinstance(record["errors"], list) or not all(isinstance(v, str) for v in record["errors"]):
        raise ValueError("invalid errors")
    capabilities = record["capabilities"]
    if not isinstance(capabilities, dict) or set(capabilities) != {
            "staging", "activation", "runtime_probe", "runtime_required"} or not all(
                isinstance(v, bool) for v in capabilities.values()):
        raise ValueError("invalid capabilities")
    return {**record, "evidence": list(record["evidence"]),
            "errors": list(record["errors"]), "capabilities": dict(capabilities)}


def from_legacy(component: str, *, attempt=None, installed_sha=None, bastion=None,
                runtime_state="unknown", checked_at=None) -> dict:
    """Adapt independent observations; attempted SHA never certifies activation."""
    recovery_strategy(component)
    if attempt is not None and not isinstance(attempt, dict):
        raise ValueError("invalid attempt")
    if bastion is not None and not isinstance(bastion, dict):
        raise ValueError("invalid Bastion evidence")
    attempt = attempt or {}
    bastion = bastion or {}
    if attempt.get("status", "never-attempted") not in (
            "never-attempted", "started", "installed", "staged", "failed"):
        raise ValueError("invalid attempt state")
    _revision(attempt.get("sha"))
    _revision(installed_sha)
    _revision(bastion.get("staged_sha"))
    _timestamp(checked_at)
    if runtime_state not in ("healthy", "unhealthy", "unknown", "not_applicable"):
        raise ValueError("invalid runtime state")
    # No trusted activation or runtime probe in the attempt journal.
    row = {"name": component, "installed_sha": installed_sha,
           "staged_sha": bastion.get("staged_sha") if component == "gway-bastion" else None,
           "release_state": "staged" if component == "gway-bastion" and
                            bastion.get("staged_sha") else None,
           "health": "unknown", "evidence": None}
    return validate(adapt_component(row, observed_at=checked_at))
