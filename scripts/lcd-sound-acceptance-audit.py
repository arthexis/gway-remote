#!/usr/bin/env python3
"""Read-only local inventory for LCD/Sound server source acceptance.

Run as the intended producer account, independently on each server. Does not
execute events, read tokens, print service environment, invoke sudo, or modify
the host. Evidence is local and must not be confused with remote acceptance.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess

INTERESTING = ("gway", "ocpp", "odoo", "codex", "github", "sound", "lcd")
COMMANDS = ("gway-lcd-sound", "gway-sound-route", "gway-lcd-route",
            "gway-remote", "sound", "lcd")


def command(argv):
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout[:65536] if p.returncode == 0 else None


def source_route_metadata(home):
    directory = Path(home) / ".config/gway-lcd-sound"
    config = directory / "server-source.json"
    token = directory / "server-source.token"
    # Only report existence and modes; never open or log token bytes.
    def mode(p):
        try:
            info = p.lstat()
        except OSError:
            return {"exists": False}
        return {"exists": True, "mode": oct(info.st_mode & 0o777),
                "owner_matches_process": info.st_uid == os.geteuid(),
                "symlink": p.is_symlink()}
    return {"directory": mode(directory), "source_config": mode(config),
            "token_file": mode(token)}


def local_commands(home):
    """Inspect the per-user install independently of the caller's PATH."""
    directory = Path(home) / ".local/bin"
    return {name: str(path) if path.is_file() and os.access(path, os.X_OK) else None
            for name in COMMANDS for path in (directory / name,)}


def main():
    current = pwd.getpwuid(os.geteuid())
    rows = []
    listed = command(["systemctl", "list-units", "--type=service",
                      "--all", "--plain", "--no-legend", "--no-pager"])
    if listed is not None:
        names = [line.split()[0] for line in listed.splitlines() if line.split()]
        for name in names:
            if not name.endswith(".service") or not any(k in name.lower() for k in INTERESTING):
                continue
            # No Environment or ExecStart: these may contain credentials.
            raw = command(["systemctl", "show", name, "--no-pager",
                           "--property=Id,User,MainPID,FragmentPath,ActiveState"])
            if raw is None:
                continue
            details = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
            rows.append({k: details.get(k, "") for k in
                         ("Id", "User", "MainPID", "FragmentPath", "ActiveState")})
    data = {"schema": 1, "host_observed": socket.gethostname(),
            "current_user": current.pw_name, "effective_uid": os.geteuid(),
            "home": current.pw_dir,
            "commands": {name: shutil.which(name) for name in COMMANDS},
            "local_commands": local_commands(current.pw_dir),
            "source_files": source_route_metadata(current.pw_dir),
            "candidate_services": rows[:100],
            "note": "Read-only local inventory; no physical event or transport validation"}
    print(json.dumps(data, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
