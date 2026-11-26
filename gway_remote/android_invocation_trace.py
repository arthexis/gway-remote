"""Bounded Android invocation evidence. No raw arguments, UI, or device identity."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
import re
import stat
import time
import uuid

_ID = re.compile(r"[0-9a-f]{32}\Z")
_ACTIVE = ContextVar("android_invocation_trace", default=None)
_MAX_EVENTS = 32
_MAX_INPUTS = 8
_MAX_BYTES = 8192
_INPUTS = frozenset({"tap", "swipe", "text", "keyevent", "other"})
_TOOLS = frozenset({"status", "capture", "ui_tree", "navigation_model",
                    "tap", "swipe", "key", "text", "tap_target", "wait_ui",
                    "scenario_run"})
_SCREENS = frozenset({"settings", "settings_search", "settings_search_results",
                      "developer_options"})
_STAGES = frozenset({"provider_entry", "device_lock_acquired", "runner_start",
                     "runner_step_begin", "runner_step_end", "runner_finish",
                     "first_preflight", "second_preflight", "dispatch_ready",
                     "transition_rejected", "post_observation", "input_attempt",
                     "input_returned", "input_error"})
_VALUES = _SCREENS | _INPUTS | frozenset({
    "unknown", "recognized", "incomplete", "ambiguous", "passed", "failed",
    "confirmed", "unconfirmed", "not_attempted", "attempted", "uncertain",
    "unsafe_device", "source_not_actionable", "target_changed", "device_changed",
    "preflight_error", "dispatch_uncertain", "verification_error",
    "destination_unconfirmed", "provider_error", "semantic_transition",
    "status", "navigation_model", "wake_if_needed", "tap_target", "key", "wait_ui"})
_FIELDS = frozenset({"source", "destination", "screen", "status", "reason",
                     "operation", "outcome", "dispatch", "kind", "empty",
                     "focused", "enabled", "target_resolved", "truncated",
                     "field_count", "action_invocations", "step"})


def valid_id(value):
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def current():
    return _ACTIVE.get()


def mark(stage, **fields):
    trace = current()
    if trace is not None:
        trace.mark(stage, **fields)


def _safe_entry(entry):
    return (type(entry) is dict and set(entry) == {"invocation_id", "tool", "kind", "monotonic_ns"}
            and valid_id(entry["invocation_id"])
            and isinstance(entry["tool"], str) and entry["tool"] in _TOOLS
            and isinstance(entry["kind"], str) and entry["kind"] in _INPUTS
            and type(entry["monotonic_ns"]) is int and entry["monotonic_ns"] >= 0)


def _read_inputs(root):
    path = root / ".recent-inputs-v1"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return []
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > _MAX_BYTES):
            raise ValueError("unsafe trace file")
        raw = stream.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise ValueError("oversized trace")
    entries = json.loads(raw)
    if type(entries) is not list or len(entries) > _MAX_INPUTS or not all(map(_safe_entry, entries)):
        raise ValueError("invalid trace entries")
    now = time.monotonic_ns()
    return [entry for entry in entries if 0 <= now - entry["monotonic_ns"] <= 600_000_000_000]


def _write_inputs(root, entries):
    # Called only while the existing private provider device lock is held.
    # A fixed temporary name bounds crash leftovers; never follow a symlink.
    temporary = root / ".recent-inputs-v1.tmp"
    try:
        info = temporary.lstat()
    except FileNotFoundError:
        pass
    else:
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError("unsafe temporary trace")
        temporary.unlink()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(entries[-_MAX_INPUTS:], stream, separators=(",", ":"))
            stream.flush()
        os.replace(temporary, root / ".recent-inputs-v1")
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class InvocationTrace:
    def __init__(self, invocation_id, tool, root):
        self.invocation_id = invocation_id if valid_id(invocation_id) else uuid.uuid4().hex
        self.origin = "transport" if valid_id(invocation_id) else "local"
        self.tool = tool
        self.root = root
        self.started = time.monotonic_ns()
        self.events = []
        self.previous = []
        self.complete = True
        self.mark("provider_entry")

    def mark(self, stage, **fields):
        if stage not in _STAGES or len(self.events) >= _MAX_EVENTS:
            self.complete = False
            return
        event = {"stage": stage, "elapsed_ms": max(0, (time.monotonic_ns() - self.started) // 1_000_000)}
        for key, value in fields.items():
            if key not in _FIELDS:
                self.complete = False
            elif type(value) is bool or value is None:
                event[key] = value
            elif type(value) is int and 0 <= value <= 100:
                event[key] = value
            elif isinstance(value, str) and value in _VALUES:
                event[key] = value
            else:
                self.complete = False
        self.events.append(event)

    def acquired(self):
        self.mark("device_lock_acquired")
        try:
            self.previous = _read_inputs(self.root)
        except (OSError, ValueError, TypeError):
            self.complete = False

    def input_attempt(self, kind):
        self.mark("input_attempt", kind=kind)
        try:
            entries = _read_inputs(self.root)
            entries.append({"invocation_id": self.invocation_id, "tool": self.tool,
                            "kind": kind, "monotonic_ns": time.monotonic_ns()})
            _write_inputs(self.root, entries)
        except (OSError, ValueError, TypeError):
            self.complete = False

    def evidence(self):
        return {"schema": "gway-android-invocation-trace/v1",
                "invocation_id": self.invocation_id, "origin": self.origin,
                "complete": self.complete, "events": list(self.events),
                "recent_input_attempts": [
                    {"invocation_id": e["invocation_id"], "tool": e["tool"],
                     "kind": e["kind"],
                     "age_at_entry_ms": max(0, (self.started - e["monotonic_ns"]) // 1_000_000)}
                    for e in self.previous]}


@contextmanager
def invocation(invocation_id, tool, root):
    trace = InvocationTrace(invocation_id, tool, root)
    token = _ACTIVE.set(trace)
    try:
        yield trace
    finally:
        _ACTIVE.reset(token)


def observation(stage, snapshot, observed, *, source=None, destination=None, target_resolved=None):
    if current() is None:
        return
    if type(snapshot) is not dict or type(snapshot.get("elements")) is not list:
        mark(stage, source=source, destination=destination, status="incomplete",
             target_resolved=target_resolved)
        return
    fields = [element for element in snapshot["elements"]
              if type(element) is dict and element.get("resource_id") ==
              "com.android.settings.intelligence:id/search_src_text"]
    field = fields[0] if len(fields) == 1 else {}
    mark(stage, source=source, destination=destination,
         status=observed.get("status"), screen=observed.get("screen"),
         truncated=snapshot.get("truncated"), field_count=min(100, len(fields)),
         empty=field.get("text") in ("", "Buscar", None) if field else None,
         focused=field.get("focused") if field else None,
         enabled=field.get("enabled") if field else None, target_resolved=target_resolved)


def annotate_transport(result, invocation_id, stage, elapsed_ms):
    """Attach bounded transport evidence to scenario responses only, not the receipt."""
    if not valid_id(invocation_id) or stage not in ("node_transport", "watchtower_transport"):
        return result
    if type(result) is not dict or type(result.get("content")) is not list or len(result["content"]) != 1:
        return result
    item = result["content"][0]
    if type(item) is not dict or item.get("type") != "text":
        return result
    value = item.get("text")
    if not isinstance(value, str) or len(value) > _MAX_BYTES:
        return result
    try:
        body = json.loads(value)
    except ValueError:
        return result
    if type(body) is not dict or not valid_id(body.get("receipt_id")):
        return result
    body[stage] = {"invocation_id": invocation_id,
                   "matched": body.get("invocation_id") == invocation_id,
                   "elapsed_ms": min(60_000, max(0, int(elapsed_ms)))}
    return {**result, "content": [{**item, "text": json.dumps(body, separators=(",", ":"))}]}
