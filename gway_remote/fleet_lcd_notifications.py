"""Independent, read-only LCD notices for explicitly approved fleet services.

No enrollment, key scanning, service mutation or unknown-node discovery.
SSH host trust is inherited from the operator's existing pinned client config.
Unreachable nodes never imply a confirmed remote service failure.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile

TARGETS = {
    "gelectriic.com": ("gway-mcp-gateway.service", "nginx.service"),
    "ocpp-abb-1": ("ocpp-reports-ingest.service", "ocpp-reports-collector.service",
                   "ocpp-csms.service"),
}
STATE = Path.home() / ".local/state/gway-remote/fleet-notifications.json"
SOUND = {"down": "critical", "unreachable": "warning",
         "degraded": "warning", "recovered": "ok"}
NOTICE_SEVERITY = {"down": "critical", "unreachable": "error",
                   "degraded": "error", "recovered": "important"}
REASONS = {"down": "SERVICE_DOWN", "unreachable": "NODE_UNREACHABLE",
           "degraded": "PROBE_UNKNOWN", "recovered": "RECOVERED"}


def probe(node, service, *, run=subprocess.run):
    """Only fixed known nodes and units; no caller-supplied commands."""
    if node not in TARGETS or service not in TARGETS[node]:
        raise ValueError("unapproved fleet target")
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=5", "-o", "ConnectionAttempts=1",
            "ubuntu@" + node, "/usr/bin/systemctl", "is-active", "--quiet", service]
    try:
        result = run(argv, timeout=9, capture_output=True, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "unreachable"
    if result.returncode == 0:
        return "healthy"
    if result.returncode == 3:
        return "down"
    if result.returncode == 255:
        return "unreachable"
    return "degraded"


def update(previous, observed, now):
    """Two separate failing probes and two healthy recoveries."""
    if observed not in ("healthy", "down", "unreachable", "degraded"):
        raise ValueError("invalid fleet observation")
    current = dict(previous or {"active": None, "last": None,
                                "bad_count": 0, "good_count": 0, "episode": ""})
    old = current["active"]
    event = None
    if observed == "healthy":
        current["good_count"] = current.get("good_count", 0) + 1
        current["bad_count"] = 0
        current["last"] = observed
        if old is not None and current["good_count"] >= 2:
            current["active"] = None
            event = "recovered"
    else:
        if current.get("last") == observed:
            current["bad_count"] = current.get("bad_count", 0) + 1
        else:
            current["bad_count"] = 1
        current["good_count"] = 0
        current["last"] = observed
        if current["bad_count"] >= 2 and old != observed:
            current["active"] = observed
            if old is None:
                current["episode"] = hashlib.sha256(
                    (now.isoformat() + ":" + observed).encode()).hexdigest()[:32]
            event = observed
    # Active incidents renew their display lease without repeating audio.
    return current, event


def event_document(node, service, state, episode):
    if node not in TARGETS or service not in TARGETS[node]:
        raise ValueError("unapproved fleet subject")
    if state not in NOTICE_SEVERITY:
        raise ValueError("invalid fleet state")
    return {
        "schema": "gway-notification/v1", "system": "fleet",
        "origin_node": "gway-001", "target_node": node,
        "subject": {"type": "service", "name": service},
        "state": state, "severity": NOTICE_SEVERITY[state],
        "reason_code": REASONS[state], "episode_id": episode,
        "expires_in": 30 if state == "recovered" else 120,
    }


def load(path):
    if not path.exists():
        return {}
    if path.is_symlink() or path.stat().st_size > 32768:
        raise ValueError("unsafe fleet state")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (type(value) is not dict or value.get("schema") != 1
            or type(value.get("checks")) is not dict):
        raise ValueError("invalid fleet state")
    return value["checks"]


def save(path, checks):
    if path.is_symlink():
        raise ValueError("unsafe fleet state path")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = (json.dumps({"schema": 1, "checks": checks}, separators=(",", ":"),
                       sort_keys=True) + "\n").encode()
    if len(data) > 32768:
        raise ValueError("fleet state over budget")
    fd, temporary = tempfile.mkstemp(prefix=".fleet-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def emit(document, *, sound=None, run=subprocess.run, home=None):
    home = Path.home() if home is None else Path(home)
    try:
        data = json.dumps(document, separators=(",", ":"), sort_keys=True)
        lcd = run([str(home / ".local/bin/lcd"), "notice", data],
                  timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  check=False)
        if sound:
            # Claimed by the saved incident state, never retried on uncertain ACK.
            run([str(home / ".local/bin/sound"), sound],
                timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False)
        return lcd.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def cycle(*, state=STATE, now=None, monitor=probe, sender=emit, allow_send=True):
    if socket.gethostname().split(".", 1)[0] != "gway-001":
        raise PermissionError("fleet health monitor is approved on gway-001 only")
    now = now or datetime.now(timezone.utc)
    state = Path(state)
    state.parent.mkdir(parents=True, exist_ok=True)
    if state.parent.is_symlink():
        raise PermissionError("unsafe fleet state directory")
    lock = Path(str(state) + ".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        checks = load(state)
        output = []
        for node, services in TARGETS.items():
            for service in services:
                key = node + "|" + service
                observed = monitor(node, service)
                previous = checks.get(key)
                next_state, transition = update(previous, observed, now)
                checks[key] = next_state
                if transition is not None:
                    output.append((event_document(node, service, transition,
                                                  next_state["episode"]),
                                   SOUND[transition]))
                elif next_state.get("active") is not None:
                    output.append((event_document(node, service, next_state["active"],
                                                  next_state["episode"]), None))
        # The journal is committed before display/audio. A crash cannot
        # duplicate a confirmed state transition after restarting the timer.
        save(state, checks)
        if allow_send:
            for document, sound in output:
                sender(document, sound=sound)
        return {"checked": len(checks), "published": len(output),
                "transitions": sum(s is not None for _, s in output)}
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only fleet LCD notifier")
    parser.add_argument("--once", action="store_true", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(cycle(allow_send=not args.dry_run), sort_keys=True))
        return 0
    except (OSError, ValueError, PermissionError, BlockingIOError):
        print(json.dumps({"status": "observer_unavailable"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
