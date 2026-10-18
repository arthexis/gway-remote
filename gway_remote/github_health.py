"""Read-only, fail-closed reader for an externally produced GitHub health snapshot."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

REPOSITORIES = (
    "arthexis/ocpp-csms",
    "arthexis/gway-remote",
    "arthexis/ocpp-simulator",
    "arthexis/gway-rfid",
    "arthexis/gway-ap-kiosk",
)
MAX_SNAPSHOT_BYTES = 256 * 1024
MAX_AGE_SECONDS = 2 * 60 * 60


def unavailable(reason):
    return {"schema_version": 1, "status": "unavailable", "reason": reason,
            "repositories": [], "alerts": []}


def read_snapshot(path=None, now=None):
    """Never poll GitHub or trigger a workflow. Only read a completed snapshot."""
    path = path or os.environ.get("GWAY_REMOTE_GITHUB_HEALTH_SNAPSHOT") or str(Path.home() / ".local/state/gway-remote/github-health.json")
    if not path:
        return unavailable("not_configured")
    try:
        source = Path(path)
        if not source.is_file() or source.stat().st_size > MAX_SNAPSHOT_BYTES:
            return unavailable("missing_or_oversized")
        with source.open("rb") as handle:
            raw = handle.read(MAX_SNAPSHOT_BYTES + 1)
        if len(raw) > MAX_SNAPSHOT_BYTES:
            return unavailable("oversized")
        document = json.loads(raw)
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            return unavailable("invalid_schema")
        if document.get("status") != "available":
            return unavailable("source_unavailable")
        repos = document.get("repositories")
        if (not isinstance(repos, list) or len(repos) != len(REPOSITORIES)
                or {r.get("name") for r in repos if isinstance(r, dict)} != set(REPOSITORIES)
                or not all(isinstance(r, dict) and r.get("pass_a_checked") is True
                           and r.get("pass_b_checked") is True for r in repos)):
            return unavailable("incomplete_scope")
        alerts = document.get("alerts")
        if (not isinstance(alerts, list) or len(alerts) > 500
                or any(not isinstance(a, dict)
                       or a.get("repository") not in REPOSITORIES
                       or a.get("state") not in ("ACTIVE", "RESOLVED")
                       or not isinstance(a.get("id"), str) for a in alerts)):
            return unavailable("invalid_alerts")
        completed = datetime.fromisoformat(document["completed_at"].replace("Z", "+00:00"))
        if completed.tzinfo is None:
            return unavailable("invalid_timestamp")
        age = ((now or datetime.now(timezone.utc)) - completed).total_seconds()
        if age < -300 or age > MAX_AGE_SECONDS:
            return unavailable("stale")
        # Never return unvalidated source fields to the mobile client.
        return {"schema_version": 1, "status": "available",
                "completed_at": document["completed_at"], "repositories": repos,
                "alerts": alerts,
                "classification_status": document.get("classification_status", "not_implemented")}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return unavailable("invalid_or_missing")
