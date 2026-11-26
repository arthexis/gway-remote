"""Node-owned, bounded ADB MCP provider for one attached USB Android device.

Uses the existing installation user and provider federation; never shells out
through Watchtower. No root, network ADB, device unlocking, or generic shell.
"""
import base64
import fcntl
import os
import stat
from contextlib import contextmanager, nullcontext
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from .android_ui_harness import UiTargetError, condition, point, poll, selector, wait_ms
from . import android_scenario_runner as scenarios
from . import android_navigation_model as navigation
from . import android_invocation_trace as diagnostics
from . import android_execution_contract as execution
from . import android_operation_journal as operations

ADB = "/usr/bin/adb"
FFMPEG = "/usr/bin/ffmpeg"
MAX_IMAGE = 140_000
MAX_RAW_IMAGE = 6_000_000
MAX_XML = 256_000


class AndroidError(ValueError):
    pass


def _tool(name, description, properties=None, required=(), *, read=False):
    return {
        "name": name, "description": description,
        "inputSchema": {
            "type": "object", "properties": properties or {},
            "required": list(required), "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": read, "destructiveHint": False},
    }


_COORD = {"type": "integer", "minimum": 0, "maximum": 4095}
TOOLS = [
    _tool("status", "Read USB device, screen state, lock state and rotation; no serial returned.", read=True),
    _tool("ui_tree", "Read bounded, password-redacted visible elements and state flags.", read=True),
    _tool("navigation_model", "Recognize a reviewed screen and suggest a route; never performs actions.",
          {"destination": {"type": "string", "enum": sorted(navigation.SCREENS)}}, read=True),
    _tool("capture", "Capture one JPEG preview with structured coordinate metadata; may contain private data.", read=True),
    _tool("tap", "Tap one validated on-screen coordinate.", {"x": _COORD, "y": _COORD}, ("x", "y")),
    _tool("swipe", "Swipe between on-screen coordinates in 100-1000 ms.",
          {"x1": _COORD, "y1": _COORD, "x2": _COORD, "y2": _COORD,
           "duration_ms": {"type": "integer", "minimum": 100, "maximum": 1000}},
          ("x1", "y1", "x2", "y2", "duration_ms")),
    _tool("key", "Press a basic navigation key; cannot unlock a locked screen.",
          {"key": {"type": "string", "enum": ["BACK", "HOME", "ENTER", "WAKEUP", "SLEEP"]}}, ("key",)),
    _tool("text", "Type up to 80 non-secret ASCII characters; never use for passwords or tokens.",
          {"value": {"type": "string", "minLength": 1, "maxLength": 80}}, ("value",)),
]
# Strictly scoped semantic helpers preserve the existing read/execute split.
_UI_ID = {"type": "string", "minLength": 1, "maxLength": 120}
_UI_STATE = {"type": "string", "enum": ["present", "absent", "checked", "selected", "focused", "enabled"]}
_UI_WAIT = {"type": "integer", "minimum": 0, "maximum": 800}
TOOLS.extend([
    _tool(
        "tap_target", "Tap one uniquely identified enabled, clickable UI node.",
        {"resource_id": _UI_ID, "expect_id": _UI_ID,
         "expect_state": _UI_STATE, "wait_ms": _UI_WAIT},
        ("resource_id",),
    ),
    _tool(
        "wait_ui", "Read a bounded settled-state condition without touching the device.",
        {"resource_id": _UI_ID, "state": _UI_STATE, "wait_ms": _UI_WAIT},
        ("resource_id", "state"), read=True,
    ),
])

# Scenario ids are immutable and reviewed in the installed release.
_SCENARIO_ID = {"type": "string", "enum": sorted(scenarios.SCENARIOS)}
_RECEIPT_ID = {"type": "string", "minLength": 32, "maxLength": 32}
TOOLS.extend([
    _tool(
        "scenario_preview", "Preview one approved, immutable Android scenario.",
        {"scenario_id": _SCENARIO_ID}, ("scenario_id",), read=True,
    ),
    _tool(
        "scenario_run", "Run one approved scenario. Action scenarios require a fresh stable lowercase 32-hex operation_id; reconcile that same ID on uncertainty, never replay input.",
        {"scenario_id": _SCENARIO_ID, "operation_id": _RECEIPT_ID}, ("scenario_id",),
    ),
    _tool(
        "scenario_status", "Read a stable scenario operation ID and its durable status; never executes.",
        {"operation_id": _RECEIPT_ID}, ("operation_id",), read=True,
    ),
    _tool(
        "scenario_reconcile", "Acknowledge an unresolved operation after verifying a reviewed physical screen; never replays it.",
        {"operation_id": _RECEIPT_ID, "expected_screen": {"type": "string", "enum": sorted(navigation.SCREENS)}},
        ("operation_id", "expected_screen"),
    ),
    _tool(
        "scenario_result", "Read a private sanitized receipt by opaque id.",
        {"receipt_id": _RECEIPT_ID}, ("receipt_id",), read=True,
    ),
])
_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def _required_args(name, arguments):
    if type(arguments) is not dict or name not in _BY_NAME:
        raise AndroidError("invalid_tool")
    schema = _BY_NAME[name]["inputSchema"]
    supplied = set(arguments)
    if name in ("tap_target", "wait_ui", "navigation_model", "scenario_run"):
        if not set(schema["required"]) <= supplied or supplied - set(schema["properties"]):
            raise AndroidError("invalid_arguments")
        if name == "tap_target" and (("expect_id" in supplied) != ("expect_state" in supplied)):
            raise AndroidError("invalid_arguments")
    elif supplied != set(schema["required"]):
        raise AndroidError("invalid_arguments")
    for key, value in arguments.items():
        spec = schema["properties"][key]
        if spec["type"] == "integer":
            if type(value) is not int or not spec["minimum"] <= value <= spec["maximum"]:
                raise AndroidError("invalid_arguments")
        elif spec["type"] == "string":
            if type(value) is not str or (("enum" in spec and value not in spec["enum"])
                     or ("minLength" in spec and not spec["minLength"] <= len(value) <= spec["maxLength"])):
                raise AndroidError("invalid_arguments")


def _ancestors(node, parents):
    while node is not None:
        yield node
        node = parents.get(node)


class Device:
    def __init__(self, run=subprocess.run):
        self.run = run

    def _call(self, argv, *, timeout=6, data=None):
        timeout = execution.limit_timeout(timeout)
        trace = diagnostics.current()
        input_kind = None
        if len(argv) >= 6 and argv[0] == ADB and argv[3:5] == ["shell", "input"]:
            input_kind = argv[5] if argv[5] in ("tap", "swipe", "text", "keyevent") else "other"
            claim = execution.operation()
            if claim is not None:
                claim.input_attempt()
            if trace is not None:
                trace.input_attempt(input_kind)
            timeout = execution.limit_timeout(timeout)
        try:
            result = self.run(argv, input=data, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            if input_kind is not None:
                diagnostics.mark("input_error", kind=input_kind)
            raise AndroidError("adb_unavailable") from exc
        if result.returncode != 0:
            if input_kind is not None:
                diagnostics.mark("input_error", kind=input_kind)
            raise AndroidError("device_command_failed")
        if input_kind is not None:
            diagnostics.mark("input_returned", kind=input_kind)
        return result.stdout

    def serial(self):
        raw = self._call([ADB, "devices", "-l"])
        lines = raw.decode("utf-8", "replace").splitlines()
        devices = [line.split() for line in lines
                   if line.strip() and not line.startswith(("List of", "*"))]
        # Never choose one device from an ambiguous set. Only physical USB ADB.
        if len(devices) != 1 or len(devices[0]) < 3:
            raise AndroidError("expected_one_usb_device")
        record = devices[0]
        if record[1] != "device" or not any(part.startswith("usb:") for part in record[2:]):
            raise AndroidError("usb_device_not_authorized")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{4,128}", record[0]):
            raise AndroidError("invalid_device_identity")
        return record[0]

    def adb(self, serial, *args, timeout=6):
        return self._call([ADB, "-s", serial, *map(str, args)], timeout=timeout)

    def size(self, serial):
        output = self.adb(serial, "shell", "wm", "size").decode("utf-8", "replace")
        dimensions = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", output)
        if not dimensions:
            raise AndroidError("screen_dimensions_unknown")
        width, height = map(int, dimensions[-1])
        if not (0 < width <= 4096 and 0 < height <= 4096):
            raise AndroidError("screen_dimensions_invalid")
        return width, height

    def screen_state(self, serial):
        """Best-effort display/lock/rotation observations, never an unlock action.

        Unknown values remain null; the established model/size response survives
        a dumpsys denial or vendor-specific output variation.
        """
        def dump(service):
            try:
                return self.adb(serial, "shell", "dumpsys", service, timeout=6).decode(
                    "utf-8", "replace")[:256_000]
            except AndroidError:
                return ""

        power = dump("power")
        display = re.search(r"Display Power:\s*state=(ON|OFF|DOZE|DOZE_SUSPEND)\b", power)
        screen_on = (display.group(1) == "ON") if display else None

        trust = dump("trust")
        current = re.search(
            r"(?m)^.*\(current\):[^\n]*\bdeviceLocked=(0|1|true|false)\b",
            trust, re.IGNORECASE)
        locked = (current.group(1).lower() in ("1", "true")) if current else None

        controls = dump("input")
        orientation = re.search(r"\bSurfaceOrientation:\s*([0-3])\b", controls)
        rotation = (int(orientation.group(1)) * 90) if orientation else None
        return {"screen_on": screen_on, "locked": locked, "rotation": rotation}

    def wake_if_needed(self, *, serial=None):
        """Wake one authorized USB device at most once; never unlock it.

        This internal execute-only helper is not an MCP tool. An unknown
        power state fails closed; any uncertain wake result is not retried.
        """
        serial = self.serial() if serial is None else serial
        initial = self.screen_state(serial)
        if initial.get("screen_on") not in (True, False):
            raise AndroidError("screen_state_unknown")
        woke = initial["screen_on"] is False
        if woke:
            self.adb(serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
            observed = self.screen_state(serial)
            if observed.get("screen_on") is not True:
                time.sleep(0.35)
                observed = self.screen_state(serial)
        else:
            observed = initial
        if observed.get("screen_on") is not True:
            raise AndroidError("screen_not_ready")
        if observed.get("locked") is not False or type(observed.get("rotation")) is not int:
            raise AndroidError("screen_not_safe")
        return {"ok": True, "woke": woke}

    def ui_tree(self, serial, *, navigation_details=False):
        path = "/sdcard/.gway-remote-ui.xml"
        try:
            self.adb(serial, "shell", "uiautomator", "dump", path, timeout=9)
            xml = self.adb(serial, "shell", "cat", path, timeout=6)
            if len(xml) > MAX_XML:
                raise AndroidError("ui_tree_too_large")
            root = ET.fromstring(xml)
            nodes = []
            parents = {child: parent for parent in root.iter() for child in parent}
            indices = {node: i for i, node in enumerate(root.iter("node"))}
            for node in root.iter("node"):
                attrs = node.attrib
                if any(ancestor.attrib.get("password") == "true" for ancestor in _ancestors(node, parents)):
                    continue
                if (any(attrs.get(k) for k in ("text", "content-desc", "resource-id"))
                        or (navigation_details and attrs.get("package") == "com.android.settings.intelligence"
                            and attrs.get("clickable") == "true")):
                    nodes.append({
                        "text": attrs.get("text", "")[:120],
                        "description": attrs.get("content-desc", "")[:120],
                        "resource_id": attrs.get("resource-id", "")[:120],
                        "bounds": attrs.get("bounds", "")[:40],
                        "clickable": attrs.get("clickable") == "true",
                        "enabled": attrs.get("enabled") == "true",
                        "checked": attrs.get("checked") == "true",
                        "selected": attrs.get("selected") == "true",
                        "focused": attrs.get("focused") == "true",
                        "scrollable": attrs.get("scrollable") == "true",
                    })
                    if navigation_details:
                        nodes[-1].update({
                            "node_index": indices[node],
                            "package": attrs.get("package", ""),
                            "class": attrs.get("class", ""),
                            "checkable": attrs.get("checkable") == "true",
                            "ancestors": [indices[a] for a in _ancestors(node, parents)
                                          if a is not node and a in indices],
                        })
                if len(nodes) >= 100:
                    break
            return {"elements": nodes, "truncated": len(nodes) >= 100}
        except ET.ParseError as exc:
            raise AndroidError("invalid_ui_tree") from exc
        finally:
            try:
                self.adb(serial, "shell", "rm", "-f", path)
            except (AndroidError, execution.DeadlineExceeded):
                pass

    def _point(self, point, size):
        x, y = point
        if not (0 <= x < size[0] and 0 <= y < size[1]):
            raise AndroidError("coordinate_out_of_bounds")

    def semantic_transition(self, source, destination):
        """Execute once, with explicit pre-dispatch and post-dispatch accounting."""
        def reject(reason):
            diagnostics.mark("transition_rejected", reason=reason)
            return {"status": "unconfirmed", "dispatched": False, "reason": reason}

        try:
            serial = self.serial()
            state = self.screen_state(serial)
            if (state.get("screen_on") is not True or state.get("locked") is not False
                    or type(state.get("rotation")) is not int):
                return reject("unsafe_device")
            width, height = self.size(serial)
            first = self.ui_tree(serial, navigation_details=True)
            target = navigation.transition_target(first, source, destination)
            if diagnostics.current() is not None:
                diagnostics.observation("first_preflight", first, navigation.observe(first),
                                        source=source, destination=destination,
                                        target_resolved=target is not None)
            if target is None:
                return reject("source_not_actionable")
            second = self.ui_tree(serial, navigation_details=True)
            second_target = navigation.transition_target(second, source, destination)
            if diagnostics.current() is not None:
                diagnostics.observation("second_preflight", second, navigation.observe(second),
                                        source=source, destination=destination,
                                        target_resolved=second_target is not None)
            if second_target != target:
                return reject("target_changed")
            name, args = target
            if name == "tap_target":
                rid = selector(args["resource_id"])
                if point(first, rid, width=width, height=height) != point(
                        second, rid, width=width, height=height):
                    return reject("target_changed")
                x, y = point(second, rid, width=width, height=height)
                command = ("tap", x, y)
            elif name == "tap_result":
                coordinate = navigation.result_point(args, width, height)
                if coordinate is None:
                    return reject("source_not_actionable")
                command = ("tap", *coordinate)
            elif name == "text" and args == {"value": "Permanecer activo"}:
                command = ("text", "Permanecer%sactivo")
            else:
                return reject("source_not_actionable")
            if (self.screen_state(serial) != state or self.size(serial) != (width, height)
                    or self.serial() != serial):
                return reject("device_changed")
        except (OSError, ValueError, RuntimeError, TimeoutError):
            return reject("preflight_error")

        # Crossing this boundary reserves one invocation even if ADB times
        # out after sending input. Never retry or misreport it as undispatched.
        diagnostics.mark("dispatch_ready", kind=command[0])
        try:
            self.adb(serial, "shell", "input", *command)
        except (OSError, ValueError, RuntimeError, TimeoutError):
            return {"status": "unconfirmed", "dispatched": True, "reason": "dispatch_uncertain"}
        try:
            previous = None
            # Search may settle asynchronously; require two consecutive
            # matching destination observations, at most three reads.
            for _ in range(3):
                if (self.screen_state(serial) != state or self.size(serial) != (width, height)
                        or self.serial() != serial):
                    return {"status": "unconfirmed", "dispatched": True, "reason": "device_changed"}
                snapshot = self.ui_tree(serial, navigation_details=True)
                current = navigation.observe(snapshot)
                diagnostics.observation("post_observation", snapshot, current,
                                        source=source, destination=destination)
                if (current == previous and current.get("status") == "recognized"
                        and current.get("screen") == destination):
                    if (self.screen_state(serial) == state and self.size(serial) == (width, height)
                            and self.serial() == serial):
                        return {"status": "confirmed", "dispatched": True}
                    return {"status": "unconfirmed", "dispatched": True, "reason": "device_changed"}
                previous = current
        except (OSError, ValueError, RuntimeError, TimeoutError):
            return {"status": "unconfirmed", "dispatched": True, "reason": "verification_error"}
        return {"status": "unconfirmed", "dispatched": True, "reason": "destination_unconfirmed"}


    def invoke(self, name, arguments):
        _required_args(name, arguments)
        if name == "text" and not re.fullmatch(
                r"[A-Za-z0-9 .,_@/-]{1,80}", arguments["value"], flags=re.ASCII):
            raise AndroidError("unsafe_text")
        if name == "scenario_preview":
            return scenarios.preview(arguments["scenario_id"])
        if name == "scenario_result":
            return scenarios.result(arguments["receipt_id"])
        if name == "scenario_run":
            return scenarios.run(arguments["scenario_id"], device=self)
        serial = self.serial()
        if name == "status":
            width, height = self.size(serial)
            model = self.adb(serial, "shell", "getprop", "ro.product.model").decode(
                "utf-8", "replace").strip()[:80]
            return {"usb": "authorized", "width": width, "height": height,
                    "model": model, **self.screen_state(serial)}
        if name == "ui_tree":
            return self.ui_tree(serial)
        if name == "navigation_model":
            state = self.screen_state(serial)
            if state.get("screen_on") is not True or state.get("locked") is not False:
                return {"schema": navigation.SCHEMA, "screen": None, "status": "screen_not_safe"}
            snapshot = self.ui_tree(serial, navigation_details=True)
            observed = navigation.observe(snapshot)
            second = self.ui_tree(serial, navigation_details=True)
            if self.screen_state(serial) != state or navigation.observe(second) != observed:
                return {"schema": navigation.SCHEMA, "screen": None, "status": "screen_changed"}
            if "destination" in arguments:
                observed["destination"] = arguments["destination"]
                observed["route"] = navigation.route(observed.get("screen"), arguments["destination"])
            return observed
        if name in ("tap_target", "wait_ui"):
            # Semantic execute taps may wake once; read-only waits never wake.
            resource_id = selector(arguments["resource_id"])
            expected_id = selector(arguments["expect_id"]) if "expect_id" in arguments else None
            expected_state = condition(arguments["expect_state"]) if "expect_state" in arguments else None
            if name == "wait_ui":
                expected_state = condition(arguments["state"])
                expected_id = resource_id
            delay = wait_ms(arguments.get("wait_ms", 0))
            wake = self.wake_if_needed(serial=serial) if name == "tap_target" else None
            initial = self.screen_state(serial)
            if (initial.get("screen_on") is not True
                    or initial.get("locked") is not False
                    or type(initial.get("rotation")) is not int):
                if name == "wait_ui":
                    return {"status": "unknown", "attempts": 0}
                raise AndroidError("screen_not_safe")
            width, height = self.size(serial)

            def snapshot():
                current = self.screen_state(serial)
                if current != initial or self.size(serial) != (width, height):
                    raise UiTargetError("screen_changed")
                return self.ui_tree(serial)

            if name == "wait_ui":
                return poll(snapshot, resource_id=expected_id,
                            state=expected_state, wait=delay)
            # A fresh tree is resolved by exact resource-id, never user text,
            # XPath, coordinates from a prior capture, or a wildcard selector.
            target_x, target_y = point(snapshot(), resource_id,
                                       width=width, height=height)
            if self.screen_state(serial) != initial:
                raise AndroidError("screen_changed")
            self.adb(serial, "shell", "input", "tap", target_x, target_y)
            if expected_id is None:
                return {"ok": True, "action": name, "verification": "unverified",
                        "wake_invocations": int(wake["woke"])}
            settled = poll(snapshot, resource_id=expected_id,
                           state=expected_state, wait=delay)
            return {"ok": True, "action": name, "verification": settled["status"],
                    "attempts": settled["attempts"],
                    "wake_invocations": int(wake["woke"])}
        if name == "capture":
            raw = self.adb(serial, "exec-out", "screencap", "-p", timeout=7)
            if len(raw) > MAX_RAW_IMAGE or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise AndroidError("invalid_screenshot")
            # The PNG IHDR gives the actual orientation at capture time.
            # A separate wm size call can race with a device rotation.
            if len(raw) < 24:
                raise AndroidError("invalid_screenshot")
            native_width = int.from_bytes(raw[16:20], "big")
            native_height = int.from_bytes(raw[20:24], "big")
            if not (0 < native_width <= 4096 and 0 < native_height <= 4096):
                raise AndroidError("invalid_screenshot")
            capture_width = 480
            # Keep the previous 480px JPEG preview and an even-scaled height.
            capture_height = max(2, 2 * round(native_height * capture_width /
                                               native_width / 2))
            if capture_height > 4096:
                raise AndroidError("invalid_screenshot")
            jpeg = self._call([
                FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error",
                "-f", "image2pipe", "-vcodec", "png", "-i", "pipe:0",
                "-vf", f"scale={capture_width}:{capture_height}", "-frames:v", "1",
                "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "10", "pipe:1",
            ], timeout=5, data=raw)
            if not jpeg.startswith(b"\xff\xd8") or not 0 < len(jpeg) <= MAX_IMAGE:
                raise AndroidError("image_limit_exceeded")
            return {
                "content": [{"type": "image", "mimeType": "image/jpeg",
                             "data": base64.b64encode(jpeg).decode("ascii")}],
                "structuredContent": {
                    "native_width": native_width, "native_height": native_height,
                    "capture_width": capture_width, "capture_height": capture_height,
                    "scale_x": native_width / capture_width,
                    "scale_y": native_height / capture_height,
                },
            }
        if name in ("tap", "swipe"):
            size = self.size(serial)
            first = (arguments["x"], arguments["y"]) if name == "tap" else (
                arguments["x1"], arguments["y1"])
            self._point(first, size)
            if name == "tap":
                args = ("tap", *first)
            else:
                second = (arguments["x2"], arguments["y2"])
                self._point(second, size)
                args = ("swipe", *first, *second, arguments["duration_ms"])
            self.adb(serial, "shell", "input", *args)
        elif name == "key":
            self.adb(serial, "shell", "input", "keyevent", "KEYCODE_" + arguments["key"])
        elif name == "text":
            value = arguments["value"]
            self.adb(serial, "shell", "input", "text", value.replace(" ", "%s"))
        return {"ok": True, "action": name}


@contextmanager
def _device_session():
    """Serialize real provider calls across processes; never wait or steal a lock."""
    directory = scenarios._private_dir(scenarios._receipt_root(), create=True)
    fd = os.open(directory / ".device.lock",
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        meta = os.fstat(fd)
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                or meta.st_mode & 0o077 or meta.st_nlink != 1):
            raise AndroidError("unsafe_device_lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AndroidError("device_busy") from exc
        yield
    finally:
        os.close(fd)


def call_tool(name, arguments, *, device=None, invocation_id=None):
    claim = None
    try:
        _required_args(name, arguments)
        if "operation_id" in arguments and not execution.valid_id(arguments["operation_id"]):
            raise AndroidError("invalid_operation_id")
        if name == "scenario_run" and device is None:
            _, digest, actions = scenarios._spec(arguments["scenario_id"])
            operation_id = arguments.get("operation_id")
            if actions and operation_id is None:
                raise AndroidError("operation_id_required")
        # Preview and receipt reads do not interact with USB. Injected devices
        # are the hermetic unit-test seam, not reachable via MCP arguments.
        session = (_device_session() if device is None and
                   name not in ("scenario_preview", "scenario_result", "scenario_status") else nullcontext())
        trace_scope = (diagnostics.invocation(invocation_id, name, scenarios._receipt_root())
                       if device is None and name not in ("scenario_preview", "scenario_result", "scenario_status")
                       else nullcontext())
        with trace_scope as trace, session:
            if trace is not None:
                trace.acquired()
            active_device = device or Device()
            if name == "scenario_status":
                result = operations.status(scenarios._receipt_root(), arguments["operation_id"])
            elif name == "scenario_reconcile":
                result = operations.reconcile(scenarios._receipt_root(), arguments["operation_id"],
                                              arguments["expected_screen"], active_device)
            elif name == "scenario_run" and device is None:
                claim, cached = (None, None)
                if operation_id is not None:
                    claim, cached = operations.begin(scenarios._receipt_root(), operation_id,
                                                     arguments["scenario_id"], digest, actions,
                                                     invocation_id=trace.invocation_id if trace else None)
                if cached is not None:
                    result = cached
                else:
                    with execution.budget(seconds=execution.RUN_SECONDS if actions else 7, claim=claim):
                        result = active_device.invoke(name, arguments)
                    if claim is not None:
                        claim.finish(result)
                        result = operations.status(scenarios._receipt_root(), operation_id)
            else:
                result = active_device.invoke(name, arguments)
        if name == "capture":
            return result
        return {"content": [{"type": "text", "text": json.dumps(result, separators=(",", ":"))}]}
    except (AndroidError, ValueError) as exc:
        code = str(exc) if isinstance(exc, (AndroidError, operations.OperationError)) else "invalid_arguments"
        if name == "scenario_run" and isinstance(arguments, dict) and execution.valid_id(arguments.get("operation_id")):
            if claim is not None or code == "device_busy":
                return execution.uncertain_result(arguments, invocation_id, "scenario_execution_uncertain" if claim else "device_busy")
        return {"content": [{"type": "text", "text": json.dumps({"error": code})}], "isError": True}
    except (OSError, RuntimeError):
        if name == "scenario_run" and isinstance(arguments, dict) and execution.valid_id(arguments.get("operation_id")):
            return execution.uncertain_result(arguments, invocation_id, "scenario_execution_uncertain")
        return {"content": [{"type": "text", "text": '{"error":"scenario_unavailable"}'}],
                "isError": True}


def handle_rpc(request, *, device=None):
    if type(request) is not dict or request.get("jsonrpc") != "2.0":
        raise AndroidError("invalid_rpc")
    if "id" not in request:
        return None
    method, params = request.get("method"), request.get("params", {})
    if method == "initialize":
        return {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                "serverInfo": {"name": "gway-android", "version": "1"}}
    if method == "tools/list" and params == {}:
        return {"tools": TOOLS}
    if method == "tools/call" and type(params) is dict:
        return call_tool(params.get("name"), params.get("arguments", {}), device=device,
                         invocation_id=request["id"])
    raise AndroidError("unknown_method")


def main():
    for line in sys.stdin.buffer:
        if len(line) > 8192:
            return 1
        try:
            request = json.loads(line)
            result = handle_rpc(request)
            if result is None:
                continue
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except (AndroidError, ValueError, TypeError, KeyError):
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32602, "message": "Invalid request"}}
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
