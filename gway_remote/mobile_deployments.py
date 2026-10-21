"""Mobile deployment contracts: read-only M1, no workflow dispatch."""
from __future__ import annotations

from .attempts import read_attempts
from .reconcile import TARGETS
from .status import installed_revision
from .target_export import export_targets

TARGET_NAMES = frozenset(name for name, _ in TARGETS)
STATES = frozenset({"requested", "unconfirmed", "queued", "running", "installed",
                    "staged", "failed", "blocked", "unknown"})


def validate_selection(arguments):
    """Strictly validate an explicit manual request, without performing it."""
    if type(arguments) is not dict or set(arguments) != {"target"}:
        raise ValueError("invalid_deployment_arguments")
    target = arguments["target"]
    if type(target) is not str or target not in TARGET_NAMES | {"all"}:
        raise ValueError("invalid_deployment_target")
    return {"target": target, "valid": True, "dispatch_enabled": True,
            "confirmation_required": True, "ci_required": True}


def overview(arguments, *, attempts_reader=read_attempts, revision_reader=installed_revision):
    if type(arguments) is not dict or arguments:
        raise ValueError("invalid_deployment_arguments")
    attempts = attempts_reader()
    targets = export_targets()["targets"]
    return {
        "schema": 1,
        "controller": {
            "name": "gway-remote",
            # A source checkout or GitHub commit date is not deployment evidence.
            "installed_sha": None,
            "last_successful_update": None,
            "evidence": "unavailable",
        },
        "targets": [{
            "name": entry["name"], "repository": entry["repository"],
            "installed_sha": revision_reader(entry["name"]),
            "last_attempt": {
                "sha": attempts[entry["name"]].get("sha"),
                "status": attempts[entry["name"]].get("status"),
                "at": attempts[entry["name"]].get("at"),
            } if entry["name"] in attempts else None,
        } for entry in targets],
        "all_supported": True,
        "dispatch_enabled": False,
    }


def progress(arguments):
    """M1 response shape; run tracking is introduced in M2/M3."""
    if type(arguments) is not dict or arguments:
        raise ValueError("invalid_deployment_arguments")
    return {"schema": 1, "run_id": None, "state": "unknown",
            "repositories": [], "events": [], "resumable": False}
