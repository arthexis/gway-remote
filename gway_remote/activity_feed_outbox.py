"""Persistent producer-local Activity Feed outbox; never performs I/O to network on enqueue."""
from __future__ import annotations

from contextlib import closing, contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import stat
import time

from .activity_feed import EventConflict, FeedCapacityError, _canonical, validate_event
from .activity_feed_quota import OUTBOX_BYTES, OUTBOX_WAL, configure, admit

MAX_PENDING = 2048
MAX_AGE = 30 * 86400
MAX_BATCH = 20


def private_directory(path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError("unsafe feed state directory")
    return path


class Outbox:
    def __init__(self, directory, *, clock=time.time, capacity=MAX_PENDING, binding=None):
        if type(capacity) is not int or not 1 <= capacity <= MAX_PENDING:
            raise ValueError("invalid outbox capacity")
        self.directory = private_directory(directory)
        self.path = self.directory / "outbox.sqlite3"
        self.clock, self.capacity = clock, capacity
        if self.path.exists() or self.path.is_symlink():
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                raise PermissionError("unsafe outbox file")
        else:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            except FileExistsError:
                pass  # another same-user publisher initialized the private directory
        with closing(self._connect()) as db:
            if db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                raise RuntimeError("outbox WAL unavailable")
            with self._write(db):
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    db.execute("""CREATE TABLE queue (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
                        event_id TEXT NOT NULL, payload TEXT NOT NULL, created INTEGER NOT NULL,
                        due INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                        state TEXT NOT NULL DEFAULT 'pending',
                        UNIQUE(source,event_id))""")
                    db.execute("CREATE INDEX queue_due ON queue(state,due,seq)")
                    db.execute("PRAGMA user_version=1")
                elif version != 1:
                    raise RuntimeError("unsupported outbox version")
                db.execute("CREATE TABLE IF NOT EXISTS route (singleton INTEGER PRIMARY KEY CHECK(singleton=1), binding TEXT NOT NULL)")
                if binding is not None:
                    old = db.execute("SELECT binding FROM route WHERE singleton=1").fetchone()
                    if old is None or old[0] != binding:
                        if db.execute("SELECT 1 FROM queue WHERE state IN ('pending','dead') LIMIT 1").fetchone():
                            raise PermissionError("outbox route changed or unbound; reconcile pending records")
                        db.execute("DELETE FROM queue WHERE state='delivered'")
                        db.execute("INSERT OR REPLACE INTO route VALUES (1,?)", (binding,))
                self.binding = binding

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=.15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            configure(db, OUTBOX_BYTES, OUTBOX_WAL)
        except BaseException:
            db.close()
            raise
        return db

    @staticmethod
    @contextmanager
    def _write(db):
        db.execute("BEGIN IMMEDIATE")
        try:
            yield
            db.commit()
        except BaseException:
            db.rollback()
            raise

    def _check_binding(self, db):
        if self.binding is not None:
            row = db.execute("SELECT binding FROM route WHERE singleton=1").fetchone()
            if not row or row[0] != self.binding:
                raise PermissionError("outbox route changed")

    def enqueue(self, event):
        event = validate_event(event)
        payload = _canonical(event)
        key = (event["source"], event["id"])
        with closing(self._connect()) as db, self._write(db):
            self._check_binding(db)
            row = db.execute("SELECT payload,state FROM queue WHERE source=? AND event_id=?", key).fetchone()
            if row:
                if row["payload"] != payload:
                    raise EventConflict("different event with same identity")
                return row["state"]
            admit(self.path, OUTBOX_WAL)
            now = int(self.clock())
            if db.execute("SELECT COUNT(*) FROM queue").fetchone()[0] >= self.capacity:
                db.execute("DELETE FROM queue WHERE seq IN (SELECT seq FROM queue WHERE state='delivered' ORDER BY seq LIMIT 1)")
                if db.execute("SELECT COUNT(*) FROM queue").fetchone()[0] >= self.capacity:
                    raise FeedCapacityError("outbox full")
            db.execute("INSERT INTO queue(source,event_id,payload,created,due) VALUES(?,?,?,?,?)",
                       (*key, payload, now, now))
            return "pending"

    def status(self):
        with closing(self._connect()) as db:
            counts = dict(db.execute("SELECT state,COUNT(*) FROM queue GROUP BY state"))
        return {key: counts.get(key, 0) for key in ("pending", "dead", "delivered")}

    def flush(self, deliver, *, limit=MAX_BATCH):
        """Single flusher; no DB write lock held across HTTPS I/O.

        deliver(event) returns delivered, retry, or dead. Exact event stays
        durable until authenticated receipt; crash after acceptance replays.
        """
        if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
            raise ValueError("invalid batch size")
        fd = os.open(self.directory / "flush.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"busy": True, "attempted": 0}
            now = int(self.clock())
            with closing(self._connect()) as db, self._write(db):
                self._check_binding(db)
                # Never replay beyond the defined 30-day window. Retain
                # expired pending/dead entries until explicit operator purge.
                db.execute("UPDATE queue SET state='dead' WHERE state='pending' AND created<=?",
                           (now - MAX_AGE,))
                db.execute("DELETE FROM queue WHERE state='delivered' AND created<=?", (now - MAX_AGE,))
                rows = db.execute("SELECT * FROM queue WHERE state='pending' AND due<=? ORDER BY due,seq LIMIT ?",
                                  (now, limit)).fetchall()
            counts = {"busy": False, "attempted": 0, "delivered": 0, "retry": 0, "dead": 0}
            for row in rows:
                if int(self.clock()) - row["created"] >= MAX_AGE:
                    outcome = "dead"
                else:
                    try:
                        outcome = deliver(json.loads(row["payload"]))
                    except (OSError, RuntimeError, ValueError):
                        outcome = "retry"
                if outcome not in ("delivered", "retry", "dead"):
                    outcome = "retry"
                attempts = row["attempts"] + 1
                delay = min(3600, 5 * (2 ** min(attempts - 1, 10)))
                with closing(self._connect()) as db, self._write(db):
                    db.execute("UPDATE queue SET state=?,attempts=?,due=? WHERE seq=? AND state='pending'",
                               ("pending" if outcome == "retry" else outcome, attempts,
                                int(self.clock()) + delay, row["seq"]))
                counts["attempted"] += 1
                counts[outcome] += 1
            return counts
        finally:
            os.close(fd)

    def purge_dead(self):
        with closing(self._connect()) as db, self._write(db):
            return db.execute("DELETE FROM queue WHERE state='dead'").rowcount


def publish_best_effort(outbox, event):
    """Producer helper: never calls network; false means not durably accepted."""
    try:
        return outbox.enqueue(event) in ("pending", "delivered")
    except (OSError, sqlite3.Error, ValueError, RuntimeError):
        return False
