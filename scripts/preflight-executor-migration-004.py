#!/usr/bin/env python3
"""Read-only preflight for the *separate* gway-004 executor migration.

Not an authorization switch. This must run as root on the physical node,
after a reviewed package with generic identity support is installed, and
only during an externally quiesced admission window. No runtime writes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sqlite3
import stat
import subprocess
import sys
from urllib.parse import quote

from gway_remote.node_exec_identity import (
    executor_path, selected_user, state_dir, validated_account,
)

NODE = "gway-004"
FROM = "gway-exec"
TO = "arthe"
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out"})


def check_old_ledger(path: Path, owner_uid: int) -> int:
    """Read the real source ledger; do not invent a fresh, empty job database."""
    path = Path(path)
    try:
        parent = path.parent.lstat()
        entry = path.lstat()
    except OSError as exc:
        raise PermissionError("executor ledger unavailable") from exc
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != owner_uid
            or parent.st_mode & 0o077):
        raise PermissionError("unsafe executor ledger directory")
    if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != owner_uid
            or entry.st_mode & 0o077):
        raise PermissionError("unsafe executor ledger file")
    uri = "file:" + quote(str(path.absolute()), safe="/") + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=3) as db:
            rows = db.execute(
                "SELECT status, COUNT(*) FROM jobs GROUP BY status"
            ).fetchall()
    except (sqlite3.Error, OSError) as exc:
        raise RuntimeError("executor ledger unreadable") from exc
    if any(type(status) is not str or status not in TERMINAL for status, _ in rows):
        # queued, running, unknown, or any malformed/novel status: no cutover.
        raise RuntimeError("unresolved executor jobs")
    return sum(count for _, count in rows)


def verify_current_relay(user: str) -> None:
    """Reuse the already reviewed exact ForceCommand/sudoers verifier."""
    script = Path(__file__).with_name("verify-exec-relay-policy.py")
    try:
        subprocess.run(
            ["/usr/bin/python3", str(script), "--user", user],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PermissionError("relay policy not verified") from exc


def preflight(*, hostname=None, euid=None, ledger=None, relay_verifier=None):
    host = socket.gethostname() if hostname is None else hostname
    uid = os.geteuid() if euid is None else euid
    if uid != 0 or host != NODE:
        raise PermissionError("not root on the authorized node")
    current = selected_user()
    if current not in (FROM, TO):
        raise PermissionError("unexpected existing executor")
    source = validated_account(FROM)
    target = validated_account(TO)
    if source.pw_uid == target.pw_uid or target.pw_uid == 0:
        raise PermissionError("executor account identities ambiguous")
    # This function exists only in the post-#617 generic runtime. Refuse to
    # change SSH to arthe while an older receiver would deny that identity.
    executor_path(TO)
    verifier = verify_current_relay if relay_verifier is None else relay_verifier
    verifier(current)
    preserved = 0
    if current == FROM:
        old_path = Path(ledger) if ledger is not None else state_dir(FROM) / "jobs.sqlite3"
        preserved = check_old_ledger(old_path, source.pw_uid)
    return {"node": NODE, "previous": current, "selected": TO,
            "status": "already_selected" if current == TO else "preflight_only",
            "preserved_terminal_receipts": preserved}


def main():
    if len(sys.argv) != 1:
        raise SystemExit("executor migration preflight takes no arguments")
    try:
        result = preflight()
    except (OSError, ValueError, PermissionError, RuntimeError):
        raise SystemExit("executor migration preflight denied") from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
