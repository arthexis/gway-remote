"""Read-only, bounded deployment diagnosis for every registered target.

A missing probe is UNKNOWN, not unhealthy. This command never restarts units.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from .logs import read_log, sanitize
from .reconcile import TARGETS
from .status import status

# Optional unit hints. Future targets work without an entry and report unknown.
SYSTEM_UNITS = {"gway-rfid": "gway-rfid.service"}
MAX_OUTPUT = 1200


def _systemd(unit):
    if not unit:
        return {"state": "not-configured"}
    try:
        result = subprocess.run(
            ["systemctl", "show", unit, "--no-pager",
             "--property=LoadState,ActiveState,SubState,Result,ExecMainStatus,NRestarts"],
            text=True, capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"state": "unavailable"}
    if result.returncode:
        return {"state": "unavailable", "error": sanitize(result.stderr)[:200]}
    values = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            if key in {"LoadState", "ActiveState", "SubState", "Result", "ExecMainStatus", "NRestarts"}:
                values[key] = value[:100]
    return values or {"state": "unavailable"}


def diagnose(name=None, *, directory=None, lines=30):
    """Return compact, sanitised diagnostics; all target names come from TARGETS."""
    names = {target for target, _ in TARGETS}
    if name is not None and name not in names:
        raise ValueError("unknown deployment target")
    if not 1 <= lines <= 100:
        raise ValueError("lines must be between 1 and 100")
    report = status() if directory is None else status(directory)
    selected = [c for c in report["components"] if name is None or c["name"] == name]
    findings = []
    for component in selected:
        item = dict(component)
        target = item["name"]
        # No directory override means the actual local appliance journal.
        snippet = read_log(name=target, lines=lines) if directory is None else read_log(directory, name=target, lines=lines)
        item["recent_installer_log"] = sanitize(snippet or "")[-MAX_OUTPUT:]
        item["systemd"] = _systemd(SYSTEM_UNITS.get(target))
        if item["installation"] in {"failed", "interrupted"}:
            item["diagnosis"] = "installation-failed"
        elif item["health"] == "unhealthy":
            item["diagnosis"] = "runtime-unhealthy"
        elif item["health"] == "unknown":
            item["diagnosis"] = "runtime-not-verified"
        else:
            item["diagnosis"] = "healthy"
        findings.append(item)
    return {"schema": "gway-remote/diagnosis/v1", "node": report["node"],
            "checked_at": report["checked_at"], "components": findings}


def format_diagnosis(report):
    lines = [f"Deployment diagnosis — {report['node']}"]
    for item in report["components"]:
        lines += ["", f"{item['name']}: {item['diagnosis']}",
                  f"  installation={item['installation']} runtime={item['health']}",
                  f"  attempted={(item['attempted_sha'] or 'unknown')[:12]} installed={(item['installed_sha'] or 'unknown')[:12]}",
                  f"  systemd={json.dumps(item['systemd'], sort_keys=True)}"]
        if item.get("error"):
            lines.append(f"  error={sanitize(str(item['error']))[:200]}")
        if item["recent_installer_log"]:
            lines.append("  installer tail (sanitized):")
            lines.extend("    " + line for line in item["recent_installer_log"].splitlines()[-10:])
    return "\n".join(lines)
