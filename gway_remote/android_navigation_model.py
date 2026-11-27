"""Small, reviewed screen graph for navigating Android without recording UI data.

Observations are ephemeral. This module never executes a gesture or persists a tree.
"""
from collections import deque
import re

SCHEMA = "gway-android-navigation/v1"

# Evidence from the Samsung SM-G950F Spanish settings UI. The model is a guide,
# not a guarantee that another Android version exposes the same destinations.
SCREENS = {
    "settings": {"markers": ("Ajustes", "Pantalla")},
    "settings_search": {"ids": ("com.android.settings.intelligence:id/search_src_text",)},
    "settings_search_results": {"markers": ("Permanecer activo",)},
    "developer_options": {"markers": ("Opciones de desarrollador", "Permanecer activo")},
}
EDGES = (
    ("settings", "settings_search", "Open Buscar"),
    ("settings_search", "settings_search_results", "Type Permanecer activo"),
    ("settings_search_results", "developer_options", "Select Permanecer activo result"),
)


_SEARCH = "com.android.settings.intelligence"
_FIELD = _SEARCH + ":id/search_src_text"
_HISTORY = _SEARCH + ":id/saved_query_header_layout"
_BREADCRUMB = _SEARCH + ":id/breadcrumb"
_QUERY = "Permanecer activo"
_BOUNDS = re.compile(r"\[(\d{1,4}),(\d{1,4})\]\[(\d{1,4}),(\d{1,4})\]\Z")


def _search_evidence(search):
    history = any(e.get("resource_id") == _HISTORY for e in search)
    breadcrumbs = [e for e in search if e.get("resource_id") == _BREADCRUMB
                   and e.get("text") == "Opciones de desarrollador"]
    titles = [e for e in search if e.get("text") == _QUERY
              and e.get("resource_id") in ("android:id/title", _SEARCH + ":id/result")]
    return history, breadcrumbs, titles


def _bounds(node):
    raw = node.get("bounds")
    match = _BOUNDS.fullmatch(raw) if isinstance(raw, str) else None
    if match is None:
        return None
    x1, y1, x2, y2 = map(int, match.groups())
    return (x1, y1, x2, y2) if x1 < x2 and y1 < y2 else None


def _contains(outer, inner):
    return (outer is not None and inner is not None
            and outer[0] <= inner[0] < inner[2] <= outer[2]
            and outer[1] <= inner[1] < inner[3] <= outer[3])


def _under(node, index):
    ancestors = node.get("ancestors")
    return isinstance(ancestors, list) and index in ancestors


def _result_ancestor(elements, title, breadcrumb):
    """Resolve the nearest unique actionable row; never tap a list or scroll container."""
    ancestors = title.get("ancestors")
    if not isinstance(ancestors, list):
        return None
    title_bounds = _bounds(title)
    for index in ancestors[:4]:
        if type(index) is not int:
            return None
        matches = [e for e in elements if e.get("node_index") == index]
        if len(matches) > 1:
            return None
        if not matches:
            continue
        row = matches[0]
        if row.get("clickable") is not True:
            continue
        if (row.get("package") != _SEARCH or row.get("enabled") is not True
                or row.get("scrollable") is not False
                or row.get("checkable") is not False
                or not _under(breadcrumb, index)
                or row.get("resource_id") in (_FIELD, _SEARCH + ":id/list_results",
                                             _SEARCH + ":id/layout_results")):
            return None
        descendants = [e for e in elements if _under(e, index)]
        if any(e is not title and (e.get("resource_id") == "android:id/title"
                                  or e.get("clickable") is True
                                  or e.get("checkable") is True)
               for e in descendants):
            return None
        row_bounds = _bounds(row)
        if not _contains(row_bounds, title_bounds) or not _contains(row_bounds, _bounds(breadcrumb)):
            return None
        # The title center is inside the verified clickable row. Preserve its
        # structural identity and both rectangles across independent observations.
        return ("tap_result", {"row_index": index, "title_index": title.get("node_index"),
                               "row_bounds": row_bounds, "title_bounds": title_bounds})
    return None


def result_point(args, width, height):
    """Internal fixed-edge target only; public tools cannot supply this payload."""
    row = args["row_bounds"]
    title = args["title_bounds"]
    if not _contains((0, 0, width, height), row) or not _contains(row, title):
        return None
    return (title[0] + title[2]) // 2, (title[1] + title[3]) // 2


def observe(snapshot):
    """Recognize one screen; reject incomplete, malformed or ambiguous trees."""
    if (type(snapshot) is not dict or snapshot.get("truncated") is not False
            or type(snapshot.get("elements")) is not list
            or len(snapshot["elements"]) > 100
            or any(type(item) is not dict for item in snapshot["elements"])):
        return {"schema": SCHEMA, "screen": None, "status": "incomplete"}
    elements = snapshot["elements"]
    settings = [e for e in elements if e.get("package") == "com.android.settings"]
    search = [e for e in elements if e.get("package") == "com.android.settings.intelligence"]
    labels = {e.get("text") for e in settings if isinstance(e.get("text"), str)}
    search_fields = [e for e in search if e.get("resource_id") ==
                     "com.android.settings.intelligence:id/search_src_text"]
    matches = []
    if {"Ajustes", "Pantalla"} <= labels:
        matches.append("settings")
    if {"Opciones de desarrollador", "Permanecer activo"} <= labels:
        matches.append("developer_options")
    if len(search_fields) == 1:
        query = search_fields[0].get("text")
        history, breadcrumbs, titles = _search_evidence(search)
        if query == _QUERY and not history and len(titles) == len(breadcrumbs) == 1:
            matches.append("settings_search_results")
        elif query in ("", "Buscar", None) and not breadcrumbs and (history or not titles):
            matches.append("settings_search")
    if len(matches) != 1:
        return {"schema": SCHEMA, "screen": None,
                "status": "unknown" if not matches else "ambiguous"}
    screen = matches[0]
    result = {"schema": SCHEMA, "screen": screen, "status": "recognized",
              "controls": []}
    if screen == "developer_options":
        titles = [e for e in settings if e.get("text") == "Permanecer activo"]
        # Require the title and switch to share a nearby structural ancestor.
        # A common distant list/root is not enough.
        if len(titles) == 1:
            title = titles[0]
            ancestors = title.get("ancestors", [])
            switches = [e for e in settings if e.get("resource_id") == "android:id/switch_widget"
                        and e.get("checkable") is True
                        and type(e.get("checked")) is bool]
            for parent in ancestors[:3]:
                candidates = [e for e in switches if parent in e.get("ancestors", [])[:3]]
                other_titles = [e for e in settings if e is not title
                                and e.get("resource_id") == title.get("resource_id")
                                and parent in e.get("ancestors", [])]
                if other_titles:
                    break
                if candidates:
                    if len(candidates) == 1 and title.get("resource_id") == "android:id/title":
                        result["controls"].append({"id": "stay_awake", "checked": candidates[0]["checked"]})
                    break
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


# Only these reviewed edges can dispatch actions inside immutable scenarios.
# Opening Settings search remains advisory until its control is validated.
EXECUTABLE_EDGES = frozenset({
    ("settings_search", "settings_search_results"),
    ("settings_search_results", "developer_options"),
})


def transition_target(snapshot, source, destination):
    """Resolve one fresh, uniquely actionable target; never dispatch here."""
    if (source, destination) not in EXECUTABLE_EDGES:
        return None
    observed = observe(snapshot)
    if observed.get("status") != "recognized" or observed.get("screen") != source:
        return None
    elements = [e for e in snapshot["elements"]
                if e.get("package") == "com.android.settings.intelligence"]
    if source == "settings_search":
        fields = [e for e in elements
                  if e.get("resource_id") == "com.android.settings.intelligence:id/search_src_text"
                  and e.get("focused") is True and e.get("enabled") is True
                  and e.get("text") in ("", "Buscar", None)]
        return ("text", {"value": "Permanecer activo"}) if len(fields) == 1 else None
    history, breadcrumbs, titles = _search_evidence(elements)
    if history or len(breadcrumbs) != 1 or len(titles) != 1:
        return None
    title = titles[0]
    if title.get("enabled") is not True:
        return None
    if title.get("clickable") is True:
        rid = title.get("resource_id")
        if rid and sum(e.get("resource_id") == rid for e in snapshot["elements"]) == 1:
            return ("tap_target", {"resource_id": rid})
        return None
    if title.get("clickable") is not False or type(title.get("node_index")) is not int:
        return None
    return _result_ancestor(snapshot["elements"], title, breadcrumbs[0])
