"""Operator-local feed maintenance. No network, credentials or production switch."""
from contextlib import closing
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import time

from .activity_feed import ActivityFeedStore
from .activity_feed_quota import CENTRAL_BYTES, CENTRAL_WAL, file_sizes

RETENTION_DAYS = 180


def existing(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("absolute database path required")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1:
        raise PermissionError("unsafe maintenance database")
    return path


def private_target(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("absolute target required")
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o077:
        raise PermissionError("private destination directory required")
    if any(Path(str(path)+s).exists() or Path(str(path)+s).is_symlink()
           for s in ("", "-wal", "-shm", "-journal")):
        raise FileExistsError("target already exists")
    return path


def readonly(path):
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)


def validate(db):
    if db.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("unsupported feed schema")
    required = {"events", "sqlite_sequence"}
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if names != required:
        raise ValueError("not an activity feed database")
    if [r[1] for r in db.execute("PRAGMA table_info(events)")] != [
            "seq", "producer", "source", "event_id", "received_at", "category", "severity", "payload"]:
        raise ValueError("invalid activity feed table")
    if db.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
        raise ValueError("feed integrity check failed")
    pages = db.execute("PRAGMA page_count").fetchone()[0]
    page = db.execute("PRAGMA page_size").fetchone()[0]
    if pages * page > CENTRAL_BYTES:
        raise ValueError("feed exceeds page budget")


def status(path):
    path = existing(path)
    with closing(readonly(path)) as db:
        validate(db)
        count, oldest, newest, seq = db.execute(
            "SELECT COUNT(*),MIN(received_at),MAX(received_at),MAX(seq) FROM events").fetchone()
        pages = db.execute("PRAGMA page_count").fetchone()[0]
        free = db.execute("PRAGMA freelist_count").fetchone()[0]
    sizes = file_sizes(path)
    return {"events": count, "oldest_received_at": oldest, "newest_received_at": newest,
            "latest_sequence": seq, "pages": pages, "free_pages": free,
            "bytes": sizes, "total_file_bytes": sum(sizes.values()),
            "database_budget": CENTRAL_BYTES, "wal_admission_budget": CENTRAL_WAL,
            "wal_pressure": sizes["wal"] >= CENTRAL_WAL}


def prune(path, *, limit=1000):
    path = existing(path)
    with closing(readonly(path)) as db:
        validate(db)
    store = ActivityFeedStore(path)
    removed = store.prune(RETENTION_DAYS, limit=limit)
    with closing(store._connect()) as db:
        busy, pages, checkpointed = db.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
    return {"removed": removed, "checkpoint_busy": busy, "wal_pages": pages,
            "checkpointed_pages": checkpointed}


def copy_database(source, destination, *, seconds=30):
    """Online consistent backup or isolated restore to a NEW private path."""
    source, destination = existing(source), private_target(destination)
    deadline = time.monotonic() + seconds
    def progress(status_code, remaining, total):
        if time.monotonic() >= deadline:
            raise TimeoutError("feed copy budget exceeded")
    fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".feed-copy-")
    os.close(fd)
    try:
        with closing(readonly(source)) as src, closing(sqlite3.connect(temporary)) as dst:
            # Never copy a non-feed SQLite database, even if it is readable.
            validate(src)
            src.backup(dst, pages=128, progress=progress, sleep=.02)
            validate(dst)
            dst.execute("PRAGMA journal_mode=DELETE")
        with open(temporary, "rb") as stream:
            os.fsync(stream.fileno())
        # Link atomically without replacing a pre-existing target.
        os.link(temporary, destination)
        os.unlink(temporary)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return {"copied": True, "bytes": destination.stat().st_size}
    finally:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(temporary+suffix).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.environ.get("GWAY_ACTIVITY_FEED_DATABASE"))
    parser.add_argument("operation", choices=("init", "status", "prune", "backup", "restore-new", "audit-grants"))
    parser.add_argument("--destination")
    args = parser.parse_args(argv)
    try:
        if args.operation == "audit-grants":
            from .activity_feed_http import load_feed_grants
            grants = load_feed_grants()
            result = {"valid": True, "grants": len(grants), "enabled": sum(g["enabled"] for g in grants.values())}
        elif not args.database:
            raise ValueError("database path required")
        elif args.operation == "init":
            path = Path(args.database)
            if not path.is_absolute() or ".." in path.parts:
                raise ValueError("absolute database required")
            if path.exists() or path.is_symlink():
                with closing(readonly(existing(path))) as db:
                    validate(db)
                result = {"initialized":True,"created":False}
            else:
                ActivityFeedStore(path)
                result = {"initialized":True,"created":True}
        elif args.operation == "status":
            result = status(args.database)
        elif args.operation == "prune":
            result = prune(args.database)
        elif args.destination:
            result = copy_database(args.database, args.destination)
        else:
            raise ValueError("destination required")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        print("feed maintenance refused or unavailable")
        return 1
