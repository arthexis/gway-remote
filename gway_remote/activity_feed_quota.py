"""SQLite page budgets and conservative sidecar admission checks.

max_page_count caps the database, not the WAL or filesystem allocation.
A dedicated filesystem/project quota is the final hard total byte boundary.
"""
from pathlib import Path
import os
import stat

CENTRAL_BYTES = 256 * 1024 * 1024
OUTBOX_BYTES = 64 * 1024 * 1024
CENTRAL_WAL = 32 * 1024 * 1024
OUTBOX_WAL = 8 * 1024 * 1024


def file_sizes(path):
    result = {}
    for label, suffix in (("database", ""), ("wal", "-wal"), ("shm", "-shm"), ("journal", "-journal")):
        p = Path(str(path) + suffix)
        try:
            info = p.lstat()
        except FileNotFoundError:
            result[label] = 0
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PermissionError("unsafe feed database sidecar")
        result[label] = info.st_size
    return result


def configure(db, maximum, wal_budget):
    page = db.execute("PRAGMA page_size").fetchone()[0]
    pages = maximum // page
    if pages < 16:
        raise ValueError("invalid page budget")
    actual = db.execute("PRAGMA max_page_count=" + str(pages)).fetchone()[0]
    if actual > pages:
        raise RuntimeError("existing feed database exceeds configured page budget")
    db.execute("PRAGMA journal_size_limit=" + str(wal_budget))
    db.execute("PRAGMA wal_autocheckpoint=256")


def admit(path, wal_budget):
    from .activity_feed import FeedCapacityError
    sizes = file_sizes(path)
    if sizes["wal"] >= wal_budget or sizes["journal"] >= wal_budget:
        raise FeedCapacityError("feed sidecar admission budget reached")
