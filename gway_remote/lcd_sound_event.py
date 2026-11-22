"""Allowlisted, at-most-once LCD/Sound receiver for the pinned SSH node protocol.

The SSH forced-command identity is the authorization boundary; this module
never listens on a socket, accepts a shell fragment, or forwards another hop.
An operator must separately review installation/allowlisting before use.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import time

SCHEMA = 1
MAX_BYTES = 8192
NODE = re.compile(r"gway-[0-9]{3,}$")
RID = re.compile(r"[0-9a-f]{32}$")
ALLOWED = {
    "lcd": {"show", "clear", "status"},
    "sound": {"play", "event", "mute", "unmute", "toggle", "status", "sequence"},
}
DEFAULT_DB = Path.home() / ".local/state/gway-lcd-sound/remote-events.sqlite3"
MAX_EVENTS = 100000


def validate(event, *, trusted_node, now=None):
    if type(event) is not dict or set(event) != {
        "schema", "node", "origin", "request_id", "expires_at",
        "device", "action", "arguments", "hops",
    }:
        raise ValueError("invalid event fields")
    if event["schema"] != SCHEMA or event["node"] != trusted_node:
        raise PermissionError("wrong receiver")
    # This protocol is intentionally a Watchtower-only pinned SSH operation.
    # General node-origin authentication is a separate future enrollment gate.
    if event["origin"] != "watchtower":
        raise PermissionError("unapproved sender origin")
    if event["origin"] == trusted_node or type(event["hops"]) is not int or event["hops"] != 0:
        raise PermissionError("remote event forwarding loop")
    if type(event["request_id"]) is not str or not RID.fullmatch(event["request_id"]):
        raise ValueError("invalid event id")
    if type(event["device"]) is not str or event["device"] not in ALLOWED:
        raise ValueError("invalid device")
    if type(event["action"]) is not str or event["action"] not in ALLOWED[event["device"]]:
        raise ValueError("invalid action")
    try:
        expiry = datetime.fromisoformat(event["expires_at"])
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid expiry") from exc
    now = now or datetime.now(timezone.utc)
    if expiry.tzinfo is None or not 0 < (expiry - now).total_seconds() <= 30:
        raise ValueError("expired or excessive event lifetime")
    a = event["arguments"]
    if type(a) is not dict:
        raise ValueError("invalid arguments")
    if event["device"] == "lcd":
        if event["action"] == "show":
            if set(a) != {"line1", "line2", "seconds"}:
                raise ValueError("invalid LCD show arguments")
            if any(type(a[k]) is not str or len(a[k]) > 160 or
                   any(ord(ch) < 32 for ch in a[k]) for k in ("line1", "line2")):
                raise ValueError("invalid LCD line")
            if type(a["seconds"]) is not int or not 1 <= a["seconds"] <= 300:
                raise ValueError("invalid LCD duration")
        elif a:
            raise ValueError("unexpected LCD arguments")
    elif event["action"] in ("status", "mute", "unmute", "toggle"):
        if a:
            raise ValueError("unexpected sound arguments")
    elif event["action"] == "play":
        if set(a) != {"name"} or type(a["name"]) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", a["name"]):
            raise ValueError("invalid sound name")
    elif event["action"] == "sequence":
        if set(a) != {"sequence"} or type(a["sequence"]) is not str or len(a["sequence"].encode("utf-8")) > 4096:
            raise ValueError("invalid sound sequence")
        try:
            data = json.loads(a["sequence"])
            if type(data) is not dict or set(data) != {"format", "notes"} or data["format"] != "gway-piano-v1":
                raise ValueError("invalid sequence format")
            notes = data["notes"]
            if type(notes) is not list or not 1 <= len(notes) <= 12:
                raise ValueError("invalid sequence length")
            for item in notes:
                if type(item) is not list or len(item) != 3 or any(type(v) not in (float, int) for v in item):
                    raise ValueError("invalid notes")
                hz, duration, pause = item
                if (not all(math.isfinite(v) for v in item)
                    or not (hz == 0 or 80 <= hz <= 4000)
                    or not (0.01 <= duration <= 0.4 and 0 <= pause <= 0.4)):
                    raise ValueError("invalid notes")
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid sound sequence") from exc
    elif event["action"] == "event":
        if set(a) - {"event", "source", "within"} or not {"event", "source"} <= set(a):
            raise ValueError("invalid event arguments")
        for key in ("event", "source"):
            if type(a[key]) is not str or not re.fullmatch(r"[a-zA-Z0-9_*.-]{1,64}", a[key]):
                raise ValueError("invalid sound event name")
        if "within" in a and (type(a["within"]) is not int or not 0 <= a["within"] <= 3600):
            raise ValueError("invalid cooldown")
    raw = json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("oversized event")
    return raw


def argv_for(event, *, dispatcher="gway-lcd-sound", sound="sound"):
    """Validated pure data -> fixed argv; never a shell."""
    a = event["arguments"]
    action = event["action"]
    if event["device"] == "lcd":
        result = [dispatcher, "lcd", action]
        if action == "show":
            result.extend([a["line1"], a["line2"], "--seconds", str(a["seconds"])])
        return result
    if action == "event":
        result = [sound, "--event", a["event"], "--source", a["source"]]
        if "within" in a:
            result.extend(["--within", str(a["within"])])
        return result
    if action == "play":
        return [dispatcher, "sound", "play", a["name"]]
    if action == "sequence":
        return [dispatcher, "sound", "play", "--sequence", a["sequence"]]
    if action == "status":
        return [dispatcher, "sound", "status", "--json"]
    return [dispatcher, "sound", action]


def _private_db(path):
    path = Path(path)
    parent = path.parent
    if parent.is_symlink() or parent.parent.is_symlink():
        raise PermissionError("receiver journal directory symlink")
    # Initialize only the receiver owner's private application state.
    # The parent ~/.local/state remains under the already chosen executor
    # account; do not install a root-managed store or change user identity.
    if not parent.exists():
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError("receiver journal directory not private")
    if path.is_symlink():
        raise PermissionError("receiver journal symlink")
    if path.exists():
        mode = path.lstat()
        if not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.geteuid() or mode.st_mode & 0o077:
            raise PermissionError("receiver journal not private")
    return path


def receive(event, *, trusted_node, db_path=DEFAULT_DB, run=subprocess.run, now=None,
            dispatcher="gway-lcd-sound", sound="sound"):
    """Claim before running: unknown outcomes never replay hardware effects."""
    raw = validate(event, trusted_node=trusted_node, now=now)
    digest = hashlib.sha256(raw).hexdigest()
    path = _private_db(db_path)
    old_mask = os.umask(0o077)
    try:
        db = sqlite3.connect(path, timeout=5)
    finally:
        os.umask(old_mask)
    try:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, output TEXT NOT NULL DEFAULT '')")
            if "output" not in {r[1] for r in db.execute("PRAGMA table_info(events)")}:
                db.execute("ALTER TABLE events ADD COLUMN output TEXT NOT NULL DEFAULT ''")
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT digest,state,output FROM events WHERE id=?", (event["request_id"],)).fetchone()
        if row:
            db.commit()
            if row[0] != digest:
                raise PermissionError("event ID reused for different payload")
            answer = {"status": row[1], "duplicate": True}
            if event["action"] == "status":
                answer["output"] = row[2]
            return answer
        # TTL is at most 30s; old IDs are invalid at the protocol gate.
        # Pruning day-old entries bounds storage without permitting replay.
        db.execute("DELETE FROM events WHERE created < ?", (time.time() - 86400,))
        if db.execute("SELECT COUNT(*) FROM events").fetchone()[0] >= MAX_EVENTS:
            db.rollback()
            raise RuntimeError("receiver journal full")
        db.execute("INSERT INTO events (id,digest,state,created) VALUES (?,?,?,?)", (event["request_id"], digest, "uncertain", time.time()))
        db.commit()
        # The local command owns motif, cooldown, mute, LCD priority and expiry.
        # Do not allow a configured sender route to forward this request again.
        env = dict(os.environ)
        env["GWAY_LCD_SOUND_FORCE_LOCAL"] = "1"
        argv = argv_for(event, dispatcher=dispatcher, sound=sound)
        try:
            proc = run(argv, capture_output=True, timeout=10, check=False, env=env)
        except (OSError, subprocess.SubprocessError):
            return {"status": "uncertain", "duplicate": False}
        status = "succeeded" if proc.returncode == 0 else "failed"
        output = ""
        if status == "succeeded" and event["action"] == "status":
            stdout = getattr(proc, "stdout", b"")
            if type(stdout) is not bytes or len(stdout) > 4096:
                raise RuntimeError("invalid device status output")
            output = stdout.decode("utf-8", errors="replace")
        with db:
            db.execute("UPDATE events SET state=?, output=? WHERE id=?",
                       (status, output, event["request_id"]))
        answer = {"status": status, "duplicate": False}
        if event["action"] == "status":
            answer["output"] = output
        return answer
    finally:
        db.close()
