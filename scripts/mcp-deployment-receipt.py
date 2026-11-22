#!/usr/bin/env python3
"""Write a private, allowlisted MCP deployment diagnostic; never emit journal text."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timezone

UNITS = ("gway-mcp-gateway.service", "gway-mcp-link.service")
PROPERTIES = ("ActiveState", "SubState", "Result", "ExecMainStatus", "NRestarts")
VALUES = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
RUN = re.compile(r"^[a-f0-9]{32}$")


def inspect_unit(unit, *, runner=subprocess.run):
    try:
        result = runner(["systemctl", "show", unit, *["--property=" + p for p in PROPERTIES]],
                        capture_output=True, text=True, timeout=5, check=True)
        pairs = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        return {key: pairs[key] if VALUES.fullmatch(pairs.get(key, "")) else "unknown"
                for key in PROPERTIES}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {key: "unknown" for key in PROPERTIES}


def failure_class(*, runner=subprocess.run):
    try:
        result = runner(["journalctl", "-u", UNITS[0], "--since=-10 minutes", "-n", "100", "--no-pager", "-o", "cat"],
                        capture_output=True, text=True, timeout=5, check=True)
        text = result.stdout[-65536:]
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    # Fixed classes only; raw errors, paths and arguments never leave this process.
    markers = (("node is not currently attested at pinned address", "node_eligibility"),
               ("ModuleNotFoundError", "import"), ("ImportError", "import"),
               ("PermissionError", "permission"), ("Address already in use", "bind"),
               ("FileNotFoundError", "missing_file"))
    for line in reversed(text.splitlines()):
        for marker, category in markers:
            if marker in line:
                return category
    return "unclassified"


def write_receipt(directory, correlation_id, stage, *, rollback="not_checked"):
    if not RUN.fullmatch(correlation_id) or stage not in {"before", "rollback"}:
        raise ValueError("invalid receipt identity")
    if rollback not in {"not_checked", "rollback_healthy", "rollback_unhealthy"}:
        raise ValueError("invalid rollback result")
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise PermissionError("unsafe receipt directory")
    receipt = {"schema": 1, "correlation_id": correlation_id, "stage": stage,
               "timestamp": datetime.now(timezone.utc).isoformat(),
               "services": {unit: inspect_unit(unit) for unit in UNITS},
               "failure_class": failure_class(), "rollback_result": rollback}
    fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(receipt, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / (correlation_id + "-" + stage + ".json"))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--correlation-id", required=True)
    parser.add_argument("--stage", choices=("before", "rollback"), required=True)
    parser.add_argument("--rollback", default="not_checked")
    args = parser.parse_args()
    write_receipt("/var/lib/gway-mcp-deploy/receipts", args.correlation_id,
                  args.stage, rollback=args.rollback)


if __name__ == "__main__":
    main()
