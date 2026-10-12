"""Read-only appliance installation and runtime health report."""
from datetime import datetime, timezone
import platform
import logging
from time import perf_counter_ns

_LOG = logging.getLogger(__name__)

from .attempts import DEFAULT_DIR, read_attempts
from .health import component_health, quick_component_check
from .reconcile import TARGETS

def status(directory=DEFAULT_DIR, probe=component_health, *, depth="deep"):
    if depth not in ("deep", "quick"):
        raise ValueError("invalid_status_depth")
    """Never deploy, restart services, or infer installed SHA from an attempt."""
    started_ns = perf_counter_ns()
    try:
        attempts = read_attempts(directory)
        journal_error = None
    except (OSError, ValueError, UnicodeError, TypeError) as exc:
        attempts = {}
        journal_error = str(exc)
    journal_ms = (perf_counter_ns() - started_ns) / 1_000_000
    components = []
    probe_durations = {}
    for name, _ in TARGETS:
        entry = attempts.get(name)
        if journal_error:
            installation, sha, at, error, log = "unknown", None, None, journal_error, None
        elif entry is None:
            installation, sha, at, error, log = "never-attempted", None, None, None, None
        else:
            raw = entry.get("status")
            installation = ("interrupted" if raw == "started" else raw
                            if raw in ("installed", "failed") else "unknown")
            sha, at, error, log = entry.get("sha"), entry.get("at"), entry.get("error"), entry.get("log")
        probe_start_ns = perf_counter_ns()
        evidence = None
        try:
            if depth == "quick":
                evidence = quick_component_check(name)
                health = "unknown"
            else:
                result = probe(name)
                health = "healthy" if result is True else "unhealthy" if result is False else "unknown"
        except Exception:
            health = "unknown"
        finally:
            probe_durations[name] = round((perf_counter_ns() - probe_start_ns) / 1_000_000, 2)
        components.append({"name": name, "evidence": evidence, "attempted_sha": sha,
                           "attempted_at": at, "installation": installation,
                           "health": health, "installed_sha": None,
                           "error": error, "log": log})
    total_ms = round((perf_counter_ns() - started_ns) / 1_000_000, 2)
    _LOG.info("status timing total_ms=%.2f journal_ms=%.2f probe_ms=%s",
              total_ms, journal_ms, probe_durations)
    return {"schema": "gway-remote/status/v1", "depth": depth, "node": platform.node(),
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
