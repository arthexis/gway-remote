"""Read-only appliance installation and runtime health report."""
from datetime import datetime, timezone
import platform
import logging
from pathlib import Path
import re
from time import perf_counter_ns

_LOG = logging.getLogger(__name__)

from .attempts import DEFAULT_DIR, read_attempts
from .health import component_health, quick_component_check
from .reconcile import TARGETS
from .probe_registry import probe_for


def installed_revision(name):
    """Read a registered active release, never infer from deployment attempts."""
    spec = probe_for(name)
    if spec.revision_file:
        evidence = Path(spec.revision_file)
        try:
            if evidence.is_symlink() or not evidence.is_file():
                return None
            candidate = evidence.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            return None
        return candidate if re.fullmatch(r"[0-9a-f]{40}", candidate) else None
    if spec.revision_from_executable and spec.executable:
        link = Path.home() / spec.executable
        if not link.is_symlink():
            return None
        try:
            resolved = link.resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        for parent in resolved.parents:
            if parent.parent.name == "releases" and re.fullmatch(r"[0-9a-f]{40}", parent.name):
                return parent.name
        return None
    if not spec.release or not spec.revision_pattern:
        return None
    link = Path.home() / spec.release
    if not link.is_symlink():
        return None
    try:
        candidate = link.resolve(strict=True).name
    except (OSError, RuntimeError):
        return None
    return candidate if re.fullmatch(spec.revision_pattern, candidate) else None

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
                           "health": health, "installed_sha": installed_revision(name),
                           "error": error, "log": log})
    total_ms = round((perf_counter_ns() - started_ns) / 1_000_000, 2)
    _LOG.info("status timing total_ms=%.2f journal_ms=%.2f probe_ms=%s",
              total_ms, journal_ms, probe_durations)
    return {"schema": "gway-remote/status/v1", "depth": depth, "node": platform.node(),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "components": components}


def format_status(report):
    rows = ["Gway Remote — " + report["node"], "",
            f'{"Component":<19} {"Attempted SHA":<13} {"Installed SHA":<14} {"Installation":<17} Health']
    for item in report["components"]:
        sha = (item["attempted_sha"] or "—")[:12]
        installed = (item.get("installed_sha") or "unknown")[:12]
        rows.append(f'{item["name"]:<19} {sha:<13} {installed:<14} {item["installation"]:<17} {item["health"]}')
        if item["error"]:
            rows.append("  Error: " + str(item["error"]))
    rows.append("")
    rows.append("Installed revision is independently read from release links when available; unknown otherwise.")
    return "\n".join(rows)
