"""MaintenanceFence V1-C1: OFFLINE SQLite receipt journal, not deployment admission.

No callers in production. The database arbitrates only cooperating offline clients;
it cannot stop an uninstrumented subprocess, worker, workflow or AgentOps action.
Digest chaining detects accidental corruption, NOT malicious forgery.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from urllib.parse import quote

from .maintenance_fence_contract import FenceError, make_claim
from .maintenance_fence_resources import ResourceError, conflicts, plan, ResourcePlan

VERSION = "1"
_HEX24 = re.compile(r"[0-9a-f]{24}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_MAX = (1 << 63) - 1
_FIELDS = frozenset(("node", "repo", "sha", "verified_principal", "source",
                     "request_id", "boot_id", "lease_until_ns"))
_STATES = frozenset(("held", "uncertain", "terminal"))


class StoreError(ValueError):
    """Fail closed without echoing user values or SQLite details."""

    def __init__(self):
        super().__init__("invalid_maintenance_fence_store_v1")


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, UnicodeError):
        raise StoreError() from None


def _digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _decode(raw):
    if type(raw) is not str:
        raise StoreError()
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise StoreError() from None
    if _json(value) != raw:
        raise StoreError()
    return value


def _int(value, *, positive=False):
    return type(value) is int and (0 < value if positive else 0 <= value) and value <= _MAX


def _identity(binding):
    if type(binding) is not dict or set(binding) != _FIELDS:
        raise StoreError()
    try:
        make_claim(**binding, generation=1)
    except (FenceError, TypeError, ValueError):
        raise StoreError() from None


def _snapshot(snapshot):
    if type(snapshot) is not dict or set(snapshot) != {
            "binding", "resources", "state", "generation", "reason", "admin",
            "evidence_digest"}:
        raise StoreError()
    binding = snapshot["binding"]
    _identity(binding)
    resources = snapshot["resources"]
    if type(resources) is not list or not resources:
        raise StoreError()
    try:
        canonical = plan(resources)
    except ResourceError:
        raise StoreError() from None
    if list(canonical.resources) != resources:
        raise StoreError()
    if any(r.split("/")[1] != binding["node"] for r in resources):
        raise StoreError()
    state = snapshot["state"]
    if (type(state) is not str or state not in _STATES
            or not _int(snapshot["generation"], positive=True)
            or type(snapshot["reason"]) is not str):
        raise StoreError()
    reason = snapshot["reason"]
    if state == "held":
        if reason != "reserved" or snapshot["admin"] is not None or snapshot["evidence_digest"] is not None:
            raise StoreError()
    elif state == "uncertain":
        if reason not in ("expired", "boot_changed") or snapshot["admin"] is not None or snapshot["evidence_digest"] is not None:
            raise StoreError()
    elif (reason != "admin_recovery"
          or type(snapshot["admin"]) is not str or not _HEX24.fullmatch(snapshot["admin"])
          or type(snapshot["evidence_digest"]) is not str
          or not _HEX64.fullmatch(snapshot["evidence_digest"])):
        raise StoreError()
    return canonical


def _private(path):
    path = Path(path)
    if not path.is_absolute():
        raise StoreError()
    parent = path.parent
    try:
        p = os.lstat(parent)
        if (not stat.S_ISDIR(p.st_mode) or p.st_uid != os.geteuid()
                or p.st_mode & 0o077 or path.is_symlink()):
            raise StoreError()
    except (OSError, ValueError):
        raise StoreError() from None
    return path


class OfflineFenceJournal:
    """Durable model only. No deployed service, socket or operational adapter."""

    def __init__(self, path):
        self.path = _private(path)

    @classmethod
    def initialize(cls, path):
        """Explicit one-time initialization; never overwrite a preexisting DB."""
        obj = cls(path)
        try:
            fd = os.open(obj.path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            with sqlite3.connect(obj.path) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=FULL")
                db.execute("BEGIN IMMEDIATE")
                db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                db.execute("CREATE TABLE journal (seq INTEGER PRIMARY KEY, event TEXT NOT NULL, request_id TEXT NOT NULL, payload TEXT NOT NULL, prev_digest TEXT NOT NULL, digest TEXT NOT NULL)")
                db.execute("CREATE TABLE requests (request_id TEXT PRIMARY KEY, payload TEXT NOT NULL, receipt_digest TEXT NOT NULL)")
                db.executemany("INSERT INTO meta VALUES (?, ?)", (("version", VERSION), ("generation", "0")))
                db.commit()
            directory = os.open(obj.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return obj
        except (OSError, sqlite3.Error):
            # A partially initialized file remains present and unusable.
            raise StoreError() from None

    def _open(self):
        _private(self.path)
        try:
            info = os.lstat(self.path)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077):
                raise StoreError()
            url = "file:" + quote(str(self.path), safe="/") + "?mode=rw"
            db = sqlite3.connect(url, uri=True, timeout=1.0)
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            if db.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
                db.close()
                raise StoreError()
            db.execute("BEGIN IMMEDIATE")
            return db
        except (OSError, sqlite3.Error):
            raise StoreError() from None

    @staticmethod
    def _check(db):
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise StoreError()
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise StoreError()
        meta = dict(db.execute("SELECT key, value FROM meta"))
        if set(meta) != {"version", "generation"} or meta["version"] != VERSION:
            raise StoreError()
        try:
            current = int(meta["generation"])
        except (ValueError, TypeError):
            raise StoreError() from None
        if not _int(current) or str(current) != meta["generation"]:
            raise StoreError()

        last, head, max_gen, records = "", 0, 0, {}
        for seq, event, request, raw, previous, digest in db.execute(
                "SELECT seq, event, request_id, payload, prev_digest, digest FROM journal ORDER BY seq"):
            if not _int(seq, positive=True) or seq != head + 1 or previous != last:
                raise StoreError()
            if type(digest) is not str or not _HEX64.fullmatch(digest):
                raise StoreError()
            snap = _decode(raw)
            _snapshot(snap)
            binding = snap["binding"]
            if request != binding["request_id"]:
                raise StoreError()
            if event not in ("reserved", "uncertain", "recovered"):
                raise StoreError()
            if digest != _digest(_json({"seq": seq, "event": event,
                                        "request_id": request, "payload": raw,
                                        "prev_digest": previous})):
                raise StoreError()
            prior = records.get(request)
            if prior is None:
                if event != "reserved" or snap["state"] != "held" or snap["reason"] != "reserved":
                    raise StoreError()
            elif prior["binding"] != binding or prior["resources"] != snap["resources"]:
                raise StoreError()
            elif event == "uncertain":
                if (prior["state"] != "held" or snap["state"] != "uncertain"
                        or prior["generation"] != snap["generation"]):
                    raise StoreError()
            elif event == "recovered":
                if (prior["state"] != "uncertain" or snap["state"] != "terminal"
                        or snap["generation"] <= prior["generation"]):
                    raise StoreError()
            else:
                raise StoreError()
            if event == "reserved" and snap["generation"] <= max_gen:
                raise StoreError()
            if event == "recovered" and snap["generation"] <= max_gen:
                raise StoreError()
            max_gen = max(max_gen, snap["generation"])
            records[request] = snap
            head, last = seq, digest
        if current != max_gen:
            raise StoreError()
        stored = {request: (payload, digest) for request, payload, digest in
                  db.execute("SELECT request_id, payload, receipt_digest FROM requests")}
        if set(stored) != set(records):
            raise StoreError()
        for request, snap in records.items():
            # Determine the exact latest journal receipt for this request.
            record = db.execute(
                "SELECT payload, digest FROM journal WHERE request_id=? ORDER BY seq DESC LIMIT 1",
                (request,)).fetchone()
            if stored[request] != record or _decode(stored[request][0]) != snap:
                raise StoreError()
        active = [(ResourcePlan(tuple(s["resources"])), s)
                  for s in records.values() if s["state"] != "terminal"]
        for i, (left, _) in enumerate(active):
            if any(conflicts(left, other) for other, __ in active[:i]):
                raise StoreError()
        return records, current, head, last

    @staticmethod
    def _append(db, seq, prev, event, snap):
        request = snap["binding"]["request_id"]
        raw = _json(snap)
        digest = _digest(_json({"seq": seq, "event": event,
                                "request_id": request, "payload": raw,
                                "prev_digest": prev}))
        db.execute("INSERT INTO journal VALUES (?, ?, ?, ?, ?, ?)",
                   (seq, event, request, raw, prev, digest))
        db.execute("INSERT INTO requests VALUES (?, ?, ?) ON CONFLICT(request_id) DO UPDATE SET payload=excluded.payload, receipt_digest=excluded.receipt_digest",
                   (request, raw, digest))
        return digest

    def _transaction(self, operation):
        db = self._open()
        try:
            records, generation, seq, last = self._check(db)
            output = operation(db, records, generation, seq, last)
            db.commit()
            return output
        except (sqlite3.Error, OSError, ResourceError, FenceError, KeyError, TypeError, ValueError):
            db.rollback()
            raise StoreError() from None
        finally:
            db.close()

    def reserve(self, *, resources, now_ns, **binding):
        """One all-or-nothing resource-set decision; NEVER an execution permit."""
        _identity(binding)
        if not _int(now_ns) or now_ns >= binding["lease_until_ns"]:
            raise StoreError()
        try:
            resources = list(plan(resources).resources)
        except ResourceError:
            raise StoreError() from None
        if any(x.split("/")[1] != binding["node"] for x in resources):
            raise StoreError()
        def apply(db, records, generation, seq, last):
            request = binding["request_id"]
            existing = records.get(request)
            if existing is not None:
                if existing["binding"] != binding or existing["resources"] != resources:
                    raise StoreError()
                return {"state": existing["state"], "generation": existing["generation"],
                        "receipt_digest": db.execute("SELECT receipt_digest FROM requests WHERE request_id=?",
                                                     (request,)).fetchone()[0]}
            # Expired or cross-boot owners remain reserved as uncertain.
            for other, snap in list(records.items()):
                if snap["state"] != "held":
                    continue
                why = ("boot_changed" if snap["binding"]["boot_id"] != binding["boot_id"]
                       else "expired" if now_ns >= snap["binding"]["lease_until_ns"] else None)
                if why is not None:
                    updated = {**snap, "state": "uncertain", "reason": why}
                    seq += 1
                    last = self._append(db, seq, last, "uncertain", updated)
                    records[other] = updated
            requested = ResourcePlan(tuple(resources))
            if any(conflicts(requested, ResourcePlan(tuple(s["resources"])))
                   for s in records.values() if s["state"] != "terminal"):
                raise StoreError()
            if generation == _MAX:
                raise StoreError()
            generation += 1
            snap = {"binding": binding, "resources": resources, "state": "held",
                    "generation": generation, "reason": "reserved",
                    "admin": None, "evidence_digest": None}
            seq += 1
            digest = self._append(db, seq, last, "reserved", snap)
            db.execute("UPDATE meta SET value=? WHERE key='generation'", (str(generation),))
            return {"state": "held", "generation": generation, "receipt_digest": digest}
        return self._transaction(apply)

    def inspect(self, request_id):
        """Validate full journal; historical state is never proof of a live worker."""
        if type(request_id) is not str:
            raise StoreError()
        def read(db, records, generation, seq, last):
            if request_id not in records:
                raise StoreError()
            s = records[request_id]
            return {"state": s["state"], "generation": s["generation"],
                    "receipt_digest": db.execute(
                        "SELECT receipt_digest FROM requests WHERE request_id=?",
                        (request_id,)).fetchone()[0]}
        return self._transaction(read)

    def observe(self, *, now_ns, boot_id):
        """Persist uncertainty on lease expiry / different boot; never release."""
        if not _int(now_ns) or type(boot_id) is not str:
            raise StoreError()
        def apply(db, records, generation, seq, last):
            changed = 0
            for snap in list(records.values()):
                if snap["state"] != "held":
                    continue
                reason = ("boot_changed" if snap["binding"]["boot_id"] != boot_id
                          else "expired" if now_ns >= snap["binding"]["lease_until_ns"] else None)
                if reason:
                    seq += 1
                    updated = {**snap, "state": "uncertain", "reason": reason}
                    last = self._append(db, seq, last, "uncertain", updated)
                    changed += 1
            return changed
        return self._transaction(apply)

    def recover(self, *, request_id, expected_digest, verified_admin, evidence_digest):
        """Offline tombstone only. External authority and quiescence are NOT checked."""
        if (type(verified_admin) is not str or not _HEX24.fullmatch(verified_admin)
                or type(expected_digest) is not str or not _HEX64.fullmatch(expected_digest)
                or type(evidence_digest) is not str or not _HEX64.fullmatch(evidence_digest)):
            raise StoreError()
        def apply(db, records, generation, seq, last):
            snap = records.get(request_id)
            if snap is None or snap["state"] != "uncertain":
                raise StoreError()
            current_digest = db.execute("SELECT receipt_digest FROM requests WHERE request_id=?",
                                        (request_id,)).fetchone()[0]
            if current_digest != expected_digest or generation == _MAX:
                raise StoreError()
            generation += 1
            updated = {**snap, "generation": generation, "state": "terminal",
                       "reason": "admin_recovery", "admin": verified_admin,
                       "evidence_digest": evidence_digest}
            digest = self._append(db, seq + 1, last, "recovered", updated)
            db.execute("UPDATE meta SET value=? WHERE key='generation'", (str(generation),))
            return {"state": "terminal", "generation": generation, "receipt_digest": digest}
        return self._transaction(apply)
