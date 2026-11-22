#!/usr/bin/env python3
"""Independent Watchtower MCP health sample; emits fixed, non-secret status only."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

UNITS = ("gway-mcp-gateway.service", "gway-mcp-link.service", "gway-mcp-private-bridge.service")
STATE = Path("/var/lib/gway-mcp-monitor/latest.json")


def unit_state(unit, runner=subprocess.run):
    try:
        out = runner(["systemctl", "show", unit, "--property=ActiveState", "--property=SubState",
                      "--property=Result", "--property=ExecMainStatus", "--property=NRestarts"],
                     capture_output=True, text=True, timeout=5, check=True).stdout
        values = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        count = values.get("NRestarts", "")
        return {"active": values.get("ActiveState") == "active",
                "restart_count": int(count) if count.isdigit() and len(count) < 10 else None,
                "exit_status": int(values["ExecMainStatus"]) if values.get("ExecMainStatus", "").isdigit() else None}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"active": False, "restart_count": None, "exit_status": None}


def http_status(url, expected, opener=urlopen):
    try:
        with opener(url, timeout=3) as response:
            return response.status == expected
    except HTTPError as exc:
        code = exc.code
        exc.close()
        return code == expected
    except (OSError, URLError, ValueError):
        return False


def failure_class(runner=subprocess.run):
    try:
        result = runner(["journalctl", "-u", UNITS[0], "--since=-10 minutes", "-n", "100",
                         "--no-pager", "-o", "cat"], capture_output=True, text=True,
                        timeout=5, check=True)
        text = result.stdout[-65536:]
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    markers = (("node is not currently attested at pinned address", "node_eligibility"),
               ("ModuleNotFoundError", "import"), ("ImportError", "import"),
               ("PermissionError", "permission"), ("Address already in use", "bind"),
               ("FileNotFoundError", "missing_file"))
    for line in reversed(text.splitlines()):
        for marker, category in markers:
            if marker in line:
                return category
    return "unclassified"


def sample(previous=None, *, reader=unit_state, probe=http_status, classify=failure_class):
    units = {unit: reader(unit) for unit in UNITS}
    restart_count = units[UNITS[0]]["restart_count"]
    prior = (previous or {}).get("gateway_restart_count")
    restart_increase = (max(0, restart_count - prior)
                        if type(restart_count) is int and type(prior) is int else None)
    gateway = probe("http://127.0.0.1:19010/mcp", 405)
    oauth = probe("http://127.0.0.1:19012/.well-known/oauth-authorization-server", 200)
    failures = []
    if not all(state["active"] for state in units.values()):
        failures.append("service_unavailable")
    if not gateway:
        failures.append("gateway_unavailable")
    if not oauth:
        failures.append("oauth_unavailable")
    if restart_increase is not None and restart_increase >= 3:
        failures.append("restart_backoff")
    return {"schema": 1, "observed_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed" if failures else "ok", "failures": failures,
            "units": units, "gateway_http": "ok" if gateway else "failed",
            "oauth_http": "ok" if oauth else "failed",
            "gateway_restart_count": restart_count, "restart_increase": restart_increase,
            "failure_class": classify() if failures else "none",
            "authenticated_external": "not_checked"}


def main():
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = STATE.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        print('{"status":"failed","failures":["unsafe_state_directory"]}')
        return 1
    try:
        previous = json.loads(STATE.read_text())
    except (OSError, ValueError):
        previous = None
    data = sample(previous)
    fd, temp = tempfile.mkstemp(prefix=".health-", dir=STATE.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temp, STATE)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print(json.dumps({"status": data["status"], "failures": data["failures"]}))
    return 0 if data["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
