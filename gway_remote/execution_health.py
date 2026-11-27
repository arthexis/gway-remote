"""Fresh, pinned execution health from existing Watchtower receipts.

Read-only: no SSH, new ledger, write or execution on inventory access.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import stat

MAX_AGE_SECONDS = 900
MAX_ROWS = 8192


def _pinned(execution):
    if (execution is None or execution.enabled is not True
            or execution.relay.enabled is not True):
        return {}
    transport = execution.relay.transport
    if hasattr(transport, "transports"):
        entries = transport.transports
        if type(entries) is not dict:
            return {}
    else:
        entries = {transport.node.node: transport}
    pins = {}
    for name, item in entries.items():
        try:
            pin = item.node
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        key = pin.host_key_sha256
        if (type(name) is str and name == pin.node and type(key) is str
                and len(key) == 64 and all(c in "0123456789abcdef" for c in key)):
            pins[name] = key
    return pins


def _rows(path):
    path = Path(path)
    parent, info = path.parent.lstat(), path.lstat()
    uid = os.geteuid()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != uid
            or parent.st_mode & 0o077 or not stat.S_ISREG(info.st_mode)
            or info.st_uid != uid or info.st_mode & 0o077
            or path.is_symlink()):
        raise PermissionError("untrusted request ledger")
    # mode=ro observes committed WAL records without creating or updating jobs.
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro",
                         uri=True, timeout=2) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute(
            "SELECT node,host_key_sha256,state,updated_at FROM requests "
            "WHERE command IN ('hostname','id -un') "
            "ORDER BY updated_at DESC LIMIT ?", (MAX_ROWS,)
        ).fetchall()
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='periodic_health_receipts'").fetchone():
            rows.extend(db.execute("SELECT node,host_key_sha256,state,updated_at FROM periodic_health_receipts WHERE state != 'busy' ORDER BY updated_at DESC LIMIT ?", (MAX_ROWS,)).fetchall())
        return rows


def recent_probes(execution, *, now=None):
    """Aggregate only sanitized, recent terminal outcomes of known safe probes."""
    try:
        pins = _pinned(execution)
        if not pins:
            return {}
        now = datetime.now(timezone.utc) if now is None else now
        if not isinstance(now, datetime) or now.tzinfo is None:
            return {}
        rows = _rows(execution.ledger.path)
    except (AttributeError, TypeError, ValueError, OSError, sqlite3.Error):
        return {}

    latest = {}
    for node, host_key, state, observed_at in rows:
        if type(node) is not str or pins.get(node) != host_key:
            continue
        try:
            at = datetime.fromisoformat(observed_at)
            age = (now - at).total_seconds()
        except (TypeError, ValueError, OverflowError):
            continue
        if at.tzinfo is None or not 0 <= age <= MAX_AGE_SECONDS:
            continue
        if node not in latest or at > latest[node][0]:
            latest[node] = (at, state, int(age))

    result = {}
    for name, (when, state, age) in latest.items():
        health = ("verified" if state == "succeeded" else
                  "degraded" if state in ("failed", "timed_out") else "unverified")
        item = {"execution_health": health}
        if state in ("succeeded", "failed", "timed_out"):
            item["last_health_probe"] = {
                "status": state, "observed_at": when.isoformat(),
                "age_seconds": age,
            }
        result[name] = item
    return result


def project_health(payload, execution):
    """Enrich admitted public data; never change admission or expose receipt data."""
    if type(payload) is not dict or execution is None:
        return payload
    if type(payload.get("nodes")) is list:
        if not payload["nodes"]:
            return payload
        probes = recent_probes(execution)
        return {**payload, "nodes": [_project(row, probes, execution) for row in payload["nodes"]]}
    if type(payload.get("node")) is str and "execute_available" in payload:
        return _project(payload, recent_probes(execution), execution)
    return payload


def _project(row, probes, execution):
    if type(row) is not dict or row.get("execute_available") is not True:
        return row
    check = getattr(execution, "_current_eligibility", None)
    if callable(check):
        try:
            check(row.get("node"))
        except (OSError, ValueError, PermissionError, KeyError, TypeError, AttributeError):
            return {**row, "execute_available": False, "execution_health": "unverified"}
    evidence = probes.get(row.get("node"))
    return {**row, **evidence} if evidence is not None else row
