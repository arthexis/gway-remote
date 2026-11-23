"""Root-only offline operator CLI for Watchtower SD preparation (#682).

No remotely callable preparation or revocation endpoint is provided here.
The private signing key stays on the card; Watchtower receives the public key.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from .deferred_enrollment import DeferredPreparations, PreparationRejected


def read_sealing_key(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("protected sealing key required")
    mode = path.stat().st_mode
    if (mode & 0o077) or path.stat().st_uid != 0:
        raise ValueError("sealing key requires root ownership and mode 0600")
    return path.read_bytes().strip()


def create_sealing_key(path: Path) -> None:
    if path.is_symlink() or not path.parent.is_dir():
        raise ValueError("unsafe key path")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(Fernet.generate_key() + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Watchtower root-only SD preparation")
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--sealing-key", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--node", required=True)
    prep.add_argument("--public-key", required=True)
    prep.add_argument("--hours", type=int, default=24)
    for name in ("status", "revoke"):
        commands.add_parser(name).add_argument("--id", required=True)
    commands.add_parser("init-key")
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error("root operator identity required")
    try:
        if args.command == "init-key":
            create_sealing_key(args.sealing_key)
            result = {"created": True}
        else:
            ledger = DeferredPreparations(
                args.ledger, sealing_key=read_sealing_key(args.sealing_key))
            if args.command == "prepare":
                result = ledger.prepare(args.node, args.public_key, hours=args.hours)
            elif args.command == "status":
                result = ledger.status(args.id)
            else:
                result = {"revoked": ledger.revoke(args.id)}
    except (OSError, ValueError, PreparationRejected) as exc:
        # Do not accidentally print a key or URL in exception messages.
        print("SD preparation rejected or unavailable", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
