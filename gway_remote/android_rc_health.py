"""Fixed read-only stable-app health navigation for the reviewed RC workflow.

No generic destination, shell, credential input, screenshots or UI logging.
The caller must hold the existing Android device session for the whole upgrade.
"""
import re
import time

from gway_remote.android_release_candidate import PACKAGE, health_is_authenticated, require

MENU = "Abrir menú de módulos"


def _snapshot(device, serial, rotation, dimensions):
    require(device.serial() == serial, "usb_identity_changed")
    state = device.screen_state(serial)
    require(state.get("screen_on") is True and state.get("locked") is False
            and state.get("rotation") == rotation and device.size(serial) == dimensions,
            "screen_changed")
    tree = device.ui_tree(serial, navigation_details=True)
    require(tree.get("truncated") is False, "health_tree_incomplete")
    elements = tree.get("elements", [])
    require(all(r.get("package") in (PACKAGE, "android", "com.android.systemui", "")
                for r in elements), "foreign_screen_visible")
    rows = [row for row in elements if row.get("package") == PACKAGE]
    require(bool(rows), "stable_app_not_visible")
    return {"elements": rows, "truncated": False}


def _unique(tree, field, value):
    rows = [r for r in tree["elements"] if r.get(field) == value and r.get("enabled") is True]
    require(len(rows) == 1, "health_target_ambiguous")
    return rows[0]


def _point(row, dimensions):
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", row.get("bounds", ""))
    require(match is not None, "health_target_bounds_invalid")
    x1, y1, x2, y2 = map(int, match.groups())
    require(0 <= x1 < x2 <= dimensions[0] and 0 <= y1 < y2 <= dimensions[1],
            "health_target_bounds_invalid")
    return {"x": (x1+x2)//2, "y": (y1+y2)//2}


def fresh_health(device, serial, *, pause=time.sleep):
    """Enter Home then System so the health request belongs to a fresh session."""
    device.wake_if_needed(serial=serial)
    state = device.screen_state(serial)
    rotation = state.get("rotation")
    require(type(rotation) is int, "screen_rotation_unknown")
    dimensions = device.size(serial)

    def observe():
        return _snapshot(device, serial, rotation, dimensions)

    def tap(tree, field, value):
        row = _unique(tree, field, value)
        # Resolve twice; do not reuse a coordinate after a change.
        target = _point(row, dimensions)
        require(_point(_unique(observe(), field, value), dimensions) == target,
                "health_target_moved")
        require(device.serial() == serial, "usb_identity_changed")
        # Use the provider's bound USB serial; do not reselect a device for input.
        device.adb(serial, "shell", "input", "tap", target["x"], target["y"])
        pause(0.35)

    require(device.serial() == serial, "usb_identity_changed")
    # Fixed manifest activity, only inside the authorized hardware workflow.
    result = device.adb(serial, "shell", "am", "start", "-W", "-n",
                        PACKAGE + "/.MainActivity", timeout=20)
    require(b"Status: ok" in result and b"Error:" not in result, "stable_launch_unconfirmed")
    tree = observe()
    tap(tree, "description", MENU)
    drawer = observe()
    _unique(drawer, "text", "System")
    tap(drawer, "text", "Inicio")
    home = observe()
    _unique(home, "text", "Inicio")
    tap(home, "description", MENU)
    drawer = observe()
    _unique(drawer, "text", "Inicio")
    tap(drawer, "text", "System")
    system = observe()
    _unique(system, "text", "Status")
    tap(system, "text", "API Health")
    for _ in range(5):
        tree = observe()
        if health_is_authenticated(tree):
            return True
        texts = {r.get("text") for r in tree["elements"]}
        if texts & {"Token is required", "Unauthorized: check your token",
                    "Access denied", "Connection failed"}:
            return False
        pause(1)
    return False
