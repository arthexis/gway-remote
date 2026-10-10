"""Read-only appliance installation and runtime health report."""
from datetime import datetime, timezone
import platform

from .attempts import DEFAULT_DIR, read_attempts
from .health import component_health
from .reconcile import TARGETS

def status(directory=DEFAULT_DIR, probe=component_health):
    """Never deploy, restart services, or infer installed SHA from an attempt."""
    try:
        attempts = read_attempts(directory)
        journal_error = None
    except (OSError, ValueError, UnicodeError, TypeError) as exc:
        attempts = {}
        journal_error = str(exc)
    components = []
    for name, _ in TARGETS:
        entry = attempts.get(name)
        if journal_error:
            installation, sha, at, error = "unknown", None, None, journal_error
        elif entry is None:
            installation, sha, at, error = "never-attempted", None, None, None
        else:
            raw = entry.get("status")
            installation = ("interrupted" if raw == "started" else raw
                            if raw in ("installed", "failed") else "unknown")
            sha, at, error = entry.get("sha"), entry.get("at"), entry.get("error")
        try:
            result = probe(name)
            health = "healthy" if result is True else "unhealthy" if result is False else "unknown"
        except Exception:
            health = "unknown"
        components.append({"name": name, "attempted_sha": sha,
                           "attempted_at": at, "installation": installation,
                           "health": health, "installed_sha": None,
                           "error": error})
    return {"schema": "gway-remote/status/v1", "node": platform.node(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "components": components}


def format_status(report):
    rows = ["Gway Remote — " + report["node"], "",
            f'{"Component":<19} {"Attempted SHA":<13} {"Installation":<17} Health']
    for item in report["components"]:
        sha = (item["attempted_sha"] or "—")[:12]
        rows.append(f'{item["name"]:<19} {sha:<13} {item["installation"]:<17} {item["health"]}')
        if item["error"]:
            rows.append("  Error: " + str(item["error"]))
    rows.append("")
    rows.append("Attempted SHA is not proof of the currently installed revision.")
    return "\n".join(rows)
