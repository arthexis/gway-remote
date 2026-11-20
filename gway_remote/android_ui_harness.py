"""Pure, bounded semantic UI contracts for the single gway-001 USB Android.

No ADB, token, filesystem access, HTTP, arbitrary selector or screenshot output.
The caller owns fresh screen state, UI capture and the actual action dispatch.
"""
import re
import time

_SELECTOR = re.compile(r"[A-Za-z0-9_.$:/-]{1,120}\Z", re.ASCII)
_BOUNDS = re.compile(r"\[(\d{1,4}),(\d{1,4})\]\[(\d{1,4}),(\d{1,4})\]\Z")
_STATES = frozenset({"present", "absent", "checked", "selected", "focused", "enabled"})
_MAX_ELEMENTS = 100


class UiTargetError(ValueError):
    """A generic non-sensitive reason for a denied UI operation."""


def selector(value):
    if type(value) is not str or not _SELECTOR.fullmatch(value):
        raise UiTargetError("invalid_ui_selector")
    return value


def condition(value):
    if type(value) is not str or value not in _STATES:
        raise UiTargetError("invalid_ui_condition")
    return value


def wait_ms(value):
    if type(value) is not int or not 0 <= value <= 800:
        raise UiTargetError("invalid_ui_wait")
    return value


def _elements(snapshot):
    if type(snapshot) is not dict or type(snapshot.get("elements")) is not list:
        raise UiTargetError("invalid_ui_snapshot")
    elements = snapshot["elements"]
    if snapshot.get("truncated") is not False or len(elements) > _MAX_ELEMENTS:
        # A partial tree must never certify uniqueness or absence.
        raise UiTargetError("incomplete_ui_snapshot")
    if any(type(item) is not dict for item in elements):
        raise UiTargetError("invalid_ui_snapshot")
    return elements


def exact_node(snapshot, *, resource_id):
    selector(resource_id)
    matches = [
        item for item in _elements(snapshot)
        if item.get("resource_id") == resource_id
    ]
    if len(matches) != 1:
        raise UiTargetError("ui_target_not_unique")
    return matches[0]


def point(snapshot, resource_id, *, width, height):
    """Choose the center of the unique live, enabled, clickable node."""
    if any(type(v) is not int or not 1 <= v <= 4096 for v in (width, height)):
        raise UiTargetError("invalid_screen_size")
    node = exact_node(snapshot, resource_id=resource_id)
    if node.get("enabled") is not True or node.get("clickable") is not True:
        raise UiTargetError("ui_target_not_actionable")
    raw = node.get("bounds")
    if type(raw) is not str:
        raise UiTargetError("invalid_ui_bounds")
    match = _BOUNDS.fullmatch(raw)
    if match is None:
        raise UiTargetError("invalid_ui_bounds")
    x1, y1, x2, y2 = map(int, match.groups())
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise UiTargetError("invalid_ui_bounds")
    return (x1 + x2) // 2, (y1 + y2) // 2


def check(snapshot, resource_id, state):
    """Return bool when decisive; fail closed on partial or ambiguous trees."""
    selector(resource_id)
    condition(state)
    matches = [
        item for item in _elements(snapshot)
        if item.get("resource_id") == resource_id
    ]
    if len(matches) > 1:
        raise UiTargetError("ui_target_not_unique")
    if state == "absent":
        return len(matches) == 0
    if state == "present":
        return len(matches) == 1
    return len(matches) == 1 and matches[0].get(state) is True


def poll(read_snapshot, *, resource_id, state, wait=0, pause=time.sleep):
    """At most two observations and one bounded delay; never repeat actions."""
    selector(resource_id)
    condition(state)
    wait_ms(wait)
    for attempt in (1, 2):
        snapshot = read_snapshot()
        try:
            if check(snapshot, resource_id, state):
                return {"status": "confirmed", "attempts": attempt}
        except UiTargetError:
            return {"status": "unknown", "attempts": attempt}
        if attempt == 1 and wait:
            pause(wait / 1000.0)
        else:
            break
    return {"status": "timeout", "attempts": attempt}
