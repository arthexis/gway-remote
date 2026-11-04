#!/usr/bin/python3
"""Durable, nonsecret receipt for the fixed operator-owned deployment service."""
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from uuid import uuid4

STATE = Path("/var/lib/gway-mcp-deploy")
RECEIPT = STATE / "status.json"

def now():
    return datetime.now(timezone.utc).isoformat()

def save(record):
    if STATE.is_symlink() or not STATE.is_dir():
        raise RuntimeError("untrusted deployment receipt directory")
    if RECEIPT.is_symlink():
        raise RuntimeError("untrusted deployment receipt file")
    temp = STATE / ("." + uuid4().hex + ".tmp")
    try:
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o640)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            os.fchmod(out.fileno(), 0o640)
            json.dump(record, out, separators=(",", ":"), sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, RECEIPT)
    finally:
        if temp.exists():
            temp.unlink()

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("begin", "finish"):
        return 2
    mode = sys.argv[1]
    if mode == "begin":
        save({"schema": 1, "application": "gway-remote", "node": "gway-001",
              "attempt_id": uuid4().hex, "state": "running",
              "started_at": now(), "finished_at": None,
              "service_result": None, "exit_status": None})
        return 0
    try:
        record = json.loads(RECEIPT.read_text(encoding="utf-8"))
        if record.get("schema") != 1 or record.get("state") != "running":
            raise ValueError("not a running receipt")
    except (OSError, ValueError, TypeError):
        record = {"schema": 1, "application": "gway-remote",
                  "node": "gway-001", "attempt_id": uuid4().hex,
                  "started_at": None}
    result = os.environ.get("SERVICE_RESULT", "unknown")
    code = os.environ.get("EXIT_STATUS", "unknown")
    record.update(state="succeeded" if result == "success" else "failed",
                  finished_at=now(), service_result=result, exit_status=code)
    save(record)
    return 0

if __name__ == "__main__":
    sys.exit(main())
