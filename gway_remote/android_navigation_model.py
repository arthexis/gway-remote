"""Small, reviewed screen graph for navigating Android without recording UI data.

Observations are ephemeral. This module never executes a gesture or persists a tree.
"""
from collections import deque
import re

SCHEMA = "gway-android-navigation/v1"
_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\Z")

# Evidence from the Samsung SM-G950F Spanish settings UI. The model is a guide,
# not a guarantee that another Android version exposes the same destinations.
SCREENS = {
    "settings": {"markers": ("Ajustes", "Pantalla")},
    "settings_search": {"ids": ("com.android.settings.intelligence:id/search_src_text",)},
    "developer_options": {"markers": ("Opciones de desarrollador", "Permanecer activo")},
}
EDGES = (
    ("settings", "settings_search", "Open Buscar"),
    ("settings_search", "developer_options", "Search for Permanecer activo and select the result"),
)


def _bounds(value):
    match = _BOUNDS.fullmatch(value) if isinstance(value, str) else None
    if not match:
        return None
    x1, y1, x2, y2 = map(int, match.groups())
    return (x1, y1, x2, y2) if x1 < x2 and y1 < y2 else None


def observe(snapshot):
    """Recognize one screen; reject incomplete, malformed or ambiguous trees."""
    if (type(snapshot) is not dict or snapshot.get("truncated") is not False
            or type(snapshot.get("elements")) is not list
            or len(snapshot["elements"]) > 100
            or any(type(item) is not dict for item in snapshot["elements"])):
        return {"schema": SCHEMA, "screen": None, "status": "incomplete"}
    elements = snapshot["elements"]
    labels = {e.get("text") for e in elements if isinstance(e.get("text"), str)}
    ids = {e.get("resource_id") for e in elements if isinstance(e.get("resource_id"), str)}
    matches = [name for name, spec in SCREENS.items()
               if all(label in labels for label in spec.get("markers", ()))
               and all(rid in ids for rid in spec.get("ids", ()))]
    if len(matches) != 1:
        return {"schema": SCHEMA, "screen": None,
                "status": "unknown" if not matches else "ambiguous"}
    screen = matches[0]
    result = {"schema": SCHEMA, "screen": screen, "status": "recognized",
              "controls": []}
    if screen == "developer_options":
        titles = [e for e in elements if e.get("text") == "Permanecer activo"]
        # Adjacent switch must be unique within the title's row. Do not infer
        # state from a title, and never treat unrelated switches as this control.
        if len(titles) == 1 and (title := _bounds(titles[0].get("bounds"))):
            switches = [e for e in elements if e.get("resource_id") == "android:id/switch_widget"
                        and (b := _bounds(e.get("bounds"))) and title[1] - 40 <= b[1] <= title[3] + 100]
            if len(switches) == 1 and type(switches[0].get("checked")) is bool:
                result["controls"].append({"id": "stay_awake", "checked": switches[0]["checked"]})
    return result


def route(start, destination):
    """Return a shortest reviewed route; actions are instructions, not commands."""
    if start not in SCREENS or destination not in SCREENS:
        return None
    queue = deque([(start, [])])
    seen = {start}
    while queue:
        current, steps = queue.popleft()
        if current == destination:
            return steps
        for source, target, action in EDGES:
            if source == current and target not in seen:
                seen.add(target)
                queue.append((target, steps + [{"from": source, "to": target, "instruction": action}]))
    return None
