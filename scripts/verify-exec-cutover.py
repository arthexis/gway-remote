#!/usr/bin/env python3
"""Read-only, fail-closed identity cutover check; run only as root via Ansible."""
import os
from pathlib import Path
import sqlite3
import sys

from gway_remote.node_exec_identity import selected_user, state_dir

def main():
    if os.geteuid() != 0 or len(sys.argv) != 2:
        raise SystemExit("root and one requested user required")
    previous = selected_user()
    requested = sys.argv[1]
    if requested not in ("arthe", "gway-exec"):
        raise SystemExit("unsupported identity")
    if previous == requested:
        print("unchanged")
        return
    db_path = state_dir(previous) / "jobs.sqlite3"
    if db_path.is_symlink():
        raise SystemExit("unsafe legacy job database")
    if not db_path.exists():
        print("no prior ledger")
        return
    try:
        with sqlite3.connect("file:" + str(db_path) + "?mode=ro", uri=True, timeout=3) as db:
            active = db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"
            ).fetchone()[0]
    except (sqlite3.Error, OSError):
        raise SystemExit("cannot validate prior executor ledger") from None
    if active:
        raise SystemExit("executor cutover refused: active jobs remain")
    print("prior ledger preserved with no active jobs")


if __name__ == "__main__":
    main()
