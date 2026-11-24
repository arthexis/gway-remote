"""Stage 1A: bounded, local-only Activity Feed contract and SQLite store."""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import json
import re
import sqlite3
from urllib.parse import urlsplit
from .activity_feed_quota import CENTRAL_BYTES, CENTRAL_WAL, configure, admit

MAX_EVENT_BYTES = 16384
MAX_PAGE = 100
MAX_ROWS = 200000
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z")
_REQUIRED = {"specversion", "id", "source", "type", "time", "data"}
_DATA_REQUIRED = {"title", "summary", "category", "severity"}
_DATA_OPTIONAL = {"node", "repository", "commit", "issue", "pr", "url", "correlation_id"}


class EventConflict(ValueError):
    """A previously stored event has different content."""


class FeedCapacityError(RuntimeError):
    """The store is full; prune according to retention policy before retrying."""


def _token(value):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError("invalid event identifier")
    return value


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("invalid event text")
    if any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError("control character in event text")
    return value


def _utc(value):
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise ValueError("expected RFC3339 timestamp")
    try:
        # Python 3.10 requires exactly three or six fractional digits.
        stamp = value.replace("Z", "+00:00")
        if int(stamp[-5:-3]) > 23 or int(stamp[-2:]) > 59:
            raise ValueError("invalid UTC offset")
        if "." in stamp:
            stamp = re.sub(r"\.(\d{1,6})(?=[+-])", lambda m: "." + m[1].ljust(6, "0"), stamp)
        parsed = datetime.fromisoformat(stamp)
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError) as exc:
        raise ValueError("invalid event timestamp") from exc


def _url(value):
    _text(value, 2048)
    if any(c.isspace() or c == chr(92) for c in value):
        raise ValueError("invalid event URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("only HTTPS links without credentials are supported")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("invalid event URL port")
    if parsed.query or parsed.fragment or "?" in value or "#" in value:
        raise ValueError("event links must not contain query or fragment")
    return value


def _source(value):
    value = _text(value, 256)
    if not re.fullmatch(r"[A-Za-z0-9._~:/-]+", value):
        raise ValueError("invalid source URI reference")
    if value.startswith("//") or value in (".", ".."):
        raise ValueError("invalid source URI reference")
    return value


def _canonical(value):
    try:
        raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("invalid event JSON") from exc
    if len(raw) > MAX_EVENT_BYTES:
        raise ValueError("event exceeds size limit")
    return raw


def validate_event(event):
    """Return normalized event; caller still owns authentication and authorization."""
    if type(event) is not dict or not _REQUIRED <= event.keys() or event.keys() - (_REQUIRED | {"subject"}):
        raise ValueError("invalid CloudEvents envelope")
    if event["specversion"] != "1.0":
        raise ValueError("unsupported CloudEvents version")
    result = {"specversion": "1.0", "id": _token(event["id"]), "source": _source(event["source"]),
              "type": _token(event["type"]), "time": _utc(event["time"])}
    if "subject" in event:
        result["subject"] = _text(event["subject"], 256)
    data = event["data"]
    if type(data) is not dict or not _DATA_REQUIRED <= data.keys() or data.keys() - (_DATA_REQUIRED | _DATA_OPTIONAL):
        raise ValueError("invalid event data fields")
    if data["severity"] not in ("info", "success", "warning", "error"):
        raise ValueError("invalid severity")
    clean = {"title": _text(data["title"], 160), "summary": _text(data["summary"], 1024),
             "category": _token(data["category"]), "severity": data["severity"]}
    for key in _DATA_OPTIONAL & data.keys():
        value = data[key]
        if key in ("issue", "pr"):
            if type(value) is not int or not 1 <= value <= 2147483647:
                raise ValueError("invalid issue or PR number")
            clean[key] = value
        elif key == "url":
            clean[key] = _url(value)
        else:
            clean[key] = _token(value)
    result["data"] = clean
    _canonical(result)
    return result


class ActivityFeedStore:
    """No network or authorization. Use only a trusted operator-selected path.

    Producer and allowed source must come from the trusted caller, never the
    untrusted envelope. A new database is initialized explicitly by construction.
    """
    def __init__(self, path, *, clock=None, max_rows=MAX_ROWS):
        if type(max_rows) is not int or not 1 <= max_rows <= MAX_ROWS:
            raise ValueError("invalid row limit")
        self.path = path
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_rows = max_rows
        with closing(self._connect()) as db:
            if db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                raise RuntimeError("activity feed requires a persistent WAL database")
            with self._write(db):
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise RuntimeError("unsupported activity feed schema")
                if version == 0:
                    db.execute("""CREATE TABLE events (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        producer TEXT NOT NULL, source TEXT NOT NULL,
                        event_id TEXT NOT NULL, received_at TEXT NOT NULL,
                        category TEXT NOT NULL, severity TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        UNIQUE(producer, source, event_id))""")
                    db.execute("CREATE INDEX events_received ON events(received_at)")
                    db.execute("PRAGMA user_version=1")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            configure(db, CENTRAL_BYTES, CENTRAL_WAL)
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

    def _now(self):
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _record(row):
        return {"seq": row["seq"], "producer": row["producer"],
                "received_at": row["received_at"], "event": json.loads(row["payload"])}

    def append(self, event, *, producer, allowed_source):
        producer = _token(producer)
        allowed_source = _source(allowed_source)
        event = validate_event(event)
        if event["source"] != allowed_source:
            raise PermissionError("event source not authorized")
        payload = _canonical(event)
        key = (producer, allowed_source, event["id"])
        with closing(self._connect()) as db, self._write(db):
            row = db.execute("SELECT * FROM events WHERE producer=? AND source=? AND event_id=?", key).fetchone()
            if row:
                if row["payload"] != payload:
                    raise EventConflict("event identity already exists")
                return self._record(row), False
            if db.execute("SELECT COUNT(*) FROM events").fetchone()[0] >= self.max_rows:
                raise FeedCapacityError("activity feed row limit reached")
            admit(self.path, CENTRAL_WAL)
            received = _utc(self._now().isoformat())
            cursor = db.execute("""INSERT INTO events
                (producer, source, event_id, received_at, category, severity, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (*key, received, event["data"]["category"], event["data"]["severity"], payload))
            row = db.execute("SELECT * FROM events WHERE seq=?", (cursor.lastrowid,)).fetchone()
            return self._record(row), True

    def list_after(self, after=0, *, limit=50, category=None):
        if type(after) is not int or not 0 <= after <= 2**63 - 1:
            raise ValueError("invalid cursor")
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
            raise ValueError("invalid page size")
        params = [after]
        sql = "SELECT * FROM events WHERE seq > ?"
        if category is not None:
            sql += " AND category=?"
            params.append(_token(category))
        params.append(limit + 1)
        with closing(self._connect()) as db:
            rows = db.execute(sql + " ORDER BY seq LIMIT ?", params).fetchall()
        items = [self._record(row) for row in rows[:limit]]
        return {"items": items, "next_cursor": items[-1]["seq"] if items else after,
                "has_more": len(rows) > limit}

    def get(self, seq):
        if type(seq) is not int or not 1 <= seq <= 2**63 - 1:
            raise ValueError("invalid event sequence")
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM events WHERE seq=?", (seq,)).fetchone()
        return self._record(row) if row else None

    def list_recent(self, *, before=None, limit=50, category=None):
        if before is not None and (type(before) is not int or not 1 <= before <= 2**63 - 1):
            raise ValueError("invalid cursor")
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
            raise ValueError("invalid page size")
        sql, params = "SELECT * FROM events WHERE 1=1", []
        if before is not None:
            sql += " AND seq < ?"
            params.append(before)
        if category is not None:
            sql += " AND category=?"
            params.append(_token(category))
        with closing(self._connect()) as db:
            rows = db.execute(sql + " ORDER BY seq DESC LIMIT ?", [*params, limit + 1]).fetchall()
        items = [self._record(row) for row in rows[:limit]]
        return {"items": items, "next_cursor": items[-1]["seq"] if items else before,
                "has_more": len(rows) > limit}

    def prune(self, retention_days=180, *, limit=1000):
        if type(retention_days) is not int or not 1 <= retention_days <= 3650:
            raise ValueError("invalid retention")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid prune batch size")
        cutoff = _utc((self._now() - timedelta(days=retention_days)).isoformat())
        with closing(self._connect()) as db, self._write(db):
            return db.execute("""DELETE FROM events WHERE seq IN
                (SELECT seq FROM events WHERE received_at < ? ORDER BY received_at, seq LIMIT ?)""",
                (cutoff, limit)).rowcount
