#!/usr/bin/env python3
"""Provision the feed wrapper and user timer under the existing account.

Run explicitly from the reviewed checkout; never issues or reads credentials
into output, never uses sudo, and defaults to installing files only.
"""
from pathlib import Path
import argparse
import os
import stat
import subprocess
import tempfile

MARKER = b"# Managed by GWay Remote Activity Feed\n"
ALIAS = b'#!/bin/sh\n' + MARKER + b'exec /usr/local/bin/gway-remote feed "$@"\n'
UNITS = ("gway-activity-feed.service", "gway-activity-feed.timer")


def _inspect(target, content, mode):
    if not target.exists() and not target.is_symlink():
        return True
    info = target.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_nlink != 1 or info.st_mode & 0o022 or info.st_size > 65536):
        raise PermissionError("unsafe existing feed provisioning target")
    previous = target.read_bytes()
    if previous != content and MARKER not in previous.splitlines(keepends=True)[:2]:
        raise PermissionError("refusing to replace unrelated file")
    return previous != content or stat.S_IMODE(info.st_mode) != mode


def _install(target, content, mode):
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = target.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
        raise PermissionError("unsafe feed provisioning directory")
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".feed-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def provision(home, unit_dir):
    home, unit_dir = Path(home), Path(unit_dir)
    targets = [(home / ".local/bin/feed", ALIAS, 0o755)]
    for unit in UNITS:
        targets.append((home / ".config/systemd/user" / unit,
                        MARKER + (unit_dir / unit).read_bytes(), 0o644))
    # Reject conflicts before modifying any file.
    changes = [item for item in targets if _inspect(*item)]
    for item in changes:
        _install(*item)
    return len(changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate", action="store_true",
                        help="Explicitly enable/start the existing user's timer")
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error("run as the existing non-root installation user")
    try:
        subprocess.run(["/usr/local/bin/gway-remote", "feed", "--check-config"],
                       check=True, timeout=10)
        changed = provision(Path.home(), Path(__file__).resolve().parents[1] / "deploy/systemd")
        if args.activate:
            if changed:
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, timeout=15)
            else:
                # Reload if a prior install-only invocation staged the files.
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, timeout=15)
            subprocess.run(["systemctl", "--user", "enable", "--now", UNITS[1]],
                           check=True, timeout=15)
        print("feed provisioning: changed_files=" + str(changed))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError):
        print("feed provisioning unavailable; review local config and user manager")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
