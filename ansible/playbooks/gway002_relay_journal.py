#!/usr/bin/env python3
"""Durable, local-only recovery journal for the #614 gway-002 SSH relay.

An operator must independently authorize the Ansible apply. This helper never
creates users, changes sshd, reloads services, or contacts another machine.
A power loss leaves a recoverable pending journal; recovery is explicit.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

ROOT = Path("/var/lib/gway002-relay-rollback")
JOURNAL = ROOT / "journal.json"
OWNER_UID = 0
PATHS = (
    Path("/etc/ssh/sshd_config.d/40-gway-exec-relay.conf"),
    Path("/etc/sudoers.d/gway-exec-relay"),
    Path("/var/lib/gway-relay/.ssh/authorized_keys"),
)


def _directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != OWNER_UID or info.st_mode & 0o022:
        raise RuntimeError("unsafe directory: " + str(path))


def _parents(path):
    for parent in reversed(path.parents):
        _directory(parent)


def _read(path):
    _parents(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != OWNER_UID or info.st_nlink != 1:
        raise RuntimeError("unsafe relay file: " + str(path))
    flags = os.O_RDONLY | os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        live = os.fstat(fd)
        if (live.st_dev, live.st_ino) != (info.st_dev, info.st_ino):
            raise RuntimeError("relay file changed during read")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read()
        return {"data": base64.b64encode(data).decode("ascii"),
                "sha256": hashlib.sha256(data).hexdigest(),
                "mode": stat.S_IMODE(live.st_mode), "gid": live.st_gid}
    finally:
        os.close(fd)


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic(path, data, mode, gid=0):
    _parents(path)
    # Never replace a symlink or an unexpected file type.
    _read(path)
    fd, name = tempfile.mkstemp(prefix=".gway002-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        os.fchown(fd, OWNER_UID, gid)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(name, path)
        _sync_directory(path.parent)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(name):
            os.unlink(name)


def _root():
    if os.geteuid() != 0:
        raise RuntimeError("root required")
    _directory(ROOT.parent)
    if ROOT.exists() or ROOT.is_symlink():
        info = ROOT.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != OWNER_UID or stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError("unsafe rollback root")
    else:
        ROOT.mkdir(mode=0o700)
        _sync_directory(ROOT.parent)


def _journal():
    record = _read(JOURNAL)
    if record is None:
        return None
    if record["mode"] != 0o600:
        raise RuntimeError("unsafe journal mode")
    content = json.loads(base64.b64decode(record["data"]))
    if content.get("version") != 1 or content.get("state") not in ("pending", "complete"):
        raise RuntimeError("invalid journal")
    if set(content.get("files", {})) != {str(p) for p in PATHS}:
        raise RuntimeError("unexpected journal paths")
    return content


def _write_journal(record):
    _atomic(JOURNAL, (json.dumps(record, sort_keys=True) + "\n").encode(), 0o600)


def prepare():
    if _journal() is not None:
        raise RuntimeError("journal exists; inspect or recover before another apply")
    files = {str(path): _read(path) for path in PATHS}
    _write_journal({"version": 1, "state": "pending", "files": files})
    print("durable relay backup ready; pending recovery journal")


def recover():
    record = _journal()
    if record is None:
        raise RuntimeError("no recovery journal")
    if record["state"] != "pending":
        raise RuntimeError("completed transaction cannot be restored implicitly")
    for path in PATHS:
        saved = record["files"][str(path)]
        _parents(path)
        if saved is None:
            _read(path)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            _sync_directory(path.parent)
        else:
            data = base64.b64decode(saved["data"], validate=True)
            if hashlib.sha256(data).hexdigest() != saved["sha256"]:
                raise RuntimeError("backup checksum mismatch")
            if saved["mode"] not in (0o440, 0o644) or not isinstance(saved["gid"], int):
                raise RuntimeError("unexpected backup metadata")
            _atomic(path, data, saved["mode"], saved["gid"])
    # Deliberately remains pending until sshd -t and service reload succeed.
    print("files restored; validate sshd and reload before finalizing")


def finish():
    record = _journal()
    if record is None or record["state"] != "pending":
        raise RuntimeError("no pending transaction")
    record["state"] = "complete"
    _write_journal(record)
    print("transaction finalized; journal retained for audit")


def status():
    record = _journal()
    print("none" if record is None else record["state"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "prepare", "recover", "finish"))
    args = parser.parse_args()
    _root()
    globals()[args.command]()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print("relay rollback: " + str(exc), file=sys.stderr)
        sys.exit(1)
