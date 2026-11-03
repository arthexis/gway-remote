"""Conservative, read-only v1 evidence adapter for legacy status rows.

This adapter does not perform I/O. Existing status API fields remain unchanged.
"""
from __future__ import annotations

from .probe_registry import probe_for
from .reconcile import TARGETS

_SCHEMA = 1


def adapt_component(row: dict, *, observed_at: str | None, depth: str = "deep") -> dict:
    name = row["name"]
    spec = probe_for(name)
    bastion = name == "gway-bastion"
    staged = row.get("staged_sha") if bastion else None
    installed = row.get("installed_sha")
    release_state = row.get("release_state") if bastion else None
    # A revision file alone does not establish activation.
    activation_verified = bool(installed) and (bastion and release_state == "activated"
                                                or not bastion and not spec.revision_file)
    if bastion and release_state == "staged" and staged and not installed:
        installation = "staged"
    elif activation_verified:
        installation = "activated"
    else:
        installation = "unknown"
    runtime_required = name != "ocpp-simulator"
    runtime = row.get("health", "unknown")
    if depth != "deep" and not bastion:
        runtime = "unknown"
    if runtime not in ("healthy", "unhealthy", "unknown", "not_applicable"):
        runtime = "unknown"
    if runtime == "not_applicable" and runtime_required:
        runtime = "unknown"
    # Staged-only Bastion has no activated runtime to check. Do not infer that an
    # activated Bastion is healthy from the release record.
    if bastion:
        runtime = "not_applicable" if installation == "staged" else "unknown"
    # The simulator is a CLI package; its executable probe is not a service
    # liveness test.
    elif name == "ocpp-simulator":
        runtime = "not_applicable"
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
        "installation_state": installation,
        "runtime_state": runtime,
        "observed_at": observed_at if depth == "deep" else None,
        "evidence": evidence,
        "errors": ["invalid_release_evidence"] if row.get("evidence") == "invalid" else [],
        "capabilities": {
            "staging": bastion,
            "activation": True,
            "runtime_probe": not bastion and name != "ocpp-simulator" and spec.kind != "unknown",
            "runtime_required": runtime_required,
        },
    }
