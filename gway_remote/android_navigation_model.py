"""Small, reviewed screen graph for navigating Android without recording UI data.

Observations are ephemeral. This module never executes a gesture or persists a tree.
"""
from collections import deque

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
        results = [e for e in search if e is not search_fields[0]
                   and e.get("text") == "Permanecer activo"]
        if query == "Permanecer activo" and len(results) == 1:
            matches.append("settings_search_results")
        elif not results and query in ("", "Buscar", None):
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
