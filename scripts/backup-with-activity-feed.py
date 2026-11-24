#!/usr/bin/env python3
"""Opt-in wrapper for the identified gway-001 recovery-card backup.

Never run from a timer or automatically; the operator explicitly chooses
--check or --write. The original script owns device selection and sudo.
The feed runs as the invoking non-root account, not the privileged child.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid

BACKUP = Path("/usr/local/bin/backup")
PIN = "24d2245ba15876001c8b50740d1f67a1a052902da6c81991ab41f6a4f42b073d"
PASS = "PASS: filesystems, recorded checksums, boot references, and completed-copy receipt"


def trusted_executable(path=BACKUP):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
            or info.st_nlink != 1 or info.st_size > 65536):
        raise PermissionError("untrusted recovery-card producer")
    if hashlib.sha256(path.read_bytes()).hexdigest() != PIN:
        raise PermissionError("backup producer changed; review and repin")


def receipt(lines, code, *, invocation, now):
    if code != 0:
        return ("failed", invocation, now)
    if PASS not in lines:
        return None
    stamps = [s.removeprefix("Backup date: ") for s in lines if s.startswith("Backup date: ")]
    if len(stamps) != 1 or len(stamps[0]) > 64:
        return None
    try:
        stamp = datetime.fromisoformat(stamps[0].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        at = stamp.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None
    # Repeated verification of the same completed copy is the same event.
    run_id = hashlib.sha256(("gway-001:recovery-card:" + at).encode()).hexdigest()[:32]
    return ("verified", run_id, at)


def emit(result, *, runner=subprocess.run):
    if result is None:
        return False
    outcome, run_id, at = result
    try:
        identity = hashlib.sha256(("gway-001:backup:" + outcome + ":" + run_id).encode()).hexdigest()
        return runner(["/usr/local/bin/gway-remote", "feed",
            "Recovery-card integrity verified" if outcome == "verified" else "Recovery-card operation failed",
            "--summary", "Offline checks only; physical boot not attested" if outcome == "verified" else "Backup operation returned failure",
            "--category", "backup", "--type", "backup." + outcome,
            "--severity", "success" if outcome == "verified" else "error",
            "--node", "gway-001", "--id", identity, "--time", at],
            timeout=1.5, check=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except Exception:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        parser.error("run as the existing non-root operator")
    trusted_executable()
    invocation = uuid.uuid4().hex
    # Preserve ordinary output for the operator; retain only two allowlisted
    # receipt lines in memory, never transmit raw backup output or paths.
    lines = []
    with subprocess.Popen([str(BACKUP), "--write" if args.write else "--check"],
                          stdout=subprocess.PIPE, text=True, errors="replace") as child:
        for line in child.stdout:
            print(line, end="", flush=True)
            clean = line.rstrip("\r\n")
            if (clean == PASS or clean.startswith("Backup date: ")) and len(clean) <= 128 and len(lines) < 3:
                lines.append(clean)
        code = child.wait()
    if os.environ.get("GWAY_ACTIVITY_FEED_EXTERNAL") == "1":
        emit(receipt(lines, code, invocation=invocation, now=datetime.now(timezone.utc).isoformat()))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
