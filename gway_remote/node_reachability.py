"""Bounded, authenticated WireGuard transport observations for enrolled peers.

A handshake means recent WG transport contact, not SSH or application health.
Missing/stale evidence remains unknown rather than inventing an offline claim.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import subprocess

FRESH_SECONDS = 240


def observe(ledger: Path, *, runner=subprocess.run, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    path = Path(ledger)
    if path.is_symlink() or not path.is_file():
        raise ValueError("enrollment ledger unavailable")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        db.execute("PRAGMA query_only=ON")
        active = dict(db.execute("SELECT public_key, device FROM devices WHERE state='active'"))
    try:
        result = runner(["wg", "show", "gway", "latest-handshakes"],
                        check=True, text=True, capture_output=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return {}
    observed = {}
    for line in result.stdout.splitlines():
        values = line.split()
        if len(values) != 2:
            return {}  # malformed observations never establish reachability
        key, raw = values
        if key not in active:
            continue
        try:
            unix = int(raw)
        except ValueError:
            return {}
        if unix <= 0:
            continue
        age = now.timestamp() - unix
        if 0 <= age <= FRESH_SECONDS:
            observed[active[key]] = {
                "reachable": "reachable",
                "observed_at": datetime.fromtimestamp(unix, timezone.utc).isoformat(),
            }
    return observed
