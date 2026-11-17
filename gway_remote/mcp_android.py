"""Node-owned, bounded ADB MCP provider for one attached USB Android device.

Uses the existing installation user and provider federation; never shells out
through Watchtower. No root, network ADB, device unlocking, or generic shell.
"""
import base64
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

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
    _tool("status", "Read the single USB Android device status; no serial or secrets returned.", read=True),
    _tool("ui_tree", "Read bounded, password-redacted visible accessibility elements.", read=True),
    _tool("capture", "Capture one reduced JPEG preview of the Android screen; may contain private data.", read=True),
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
_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def _required_args(name, arguments):
    if type(arguments) is not dict or name not in _BY_NAME:
        raise AndroidError("invalid_tool")
    schema = _BY_NAME[name]["inputSchema"]
    if set(arguments) != set(schema["required"]):
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


class Device:
    def __init__(self, run=subprocess.run):
        self.run = run

    def _call(self, argv, *, timeout=6, data=None):
        try:
            result = self.run(argv, input=data, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AndroidError("adb_unavailable") from exc
        if result.returncode != 0:
            raise AndroidError("device_command_failed")
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

    def _point(self, point, size):
        x, y = point
        if not (0 <= x < size[0] and 0 <= y < size[1]):
            raise AndroidError("coordinate_out_of_bounds")

    def invoke(self, name, arguments):
        _required_args(name, arguments)
        if name == "text" and not re.fullmatch(
                r"[A-Za-z0-9 .,_@/-]{1,80}", arguments["value"], flags=re.ASCII):
            raise AndroidError("unsafe_text")
        serial = self.serial()
        if name == "status":
            width, height = self.size(serial)
            model = self.adb(serial, "shell", "getprop", "ro.product.model").decode(
                "utf-8", "replace").strip()[:80]
            return {"usb": "authorized", "width": width, "height": height, "model": model}
        if name == "ui_tree":
            path = "/sdcard/.gway-remote-ui.xml"
            try:
                self.adb(serial, "shell", "uiautomator", "dump", path, timeout=9)
                xml = self.adb(serial, "shell", "cat", path, timeout=6)
                if len(xml) > MAX_XML:
                    raise AndroidError("ui_tree_too_large")
                root = ET.fromstring(xml)
                nodes = []
                for node in root.iter("node"):
                    attrs = node.attrib
                    if attrs.get("password") == "true":
                        continue
                    if any(attrs.get(k) for k in ("text", "content-desc", "resource-id")):
                        nodes.append({
                            "text": attrs.get("text", "")[:120],
                            "description": attrs.get("content-desc", "")[:120],
                            "resource_id": attrs.get("resource-id", "")[:120],
                            "bounds": attrs.get("bounds", "")[:40],
                            "clickable": attrs.get("clickable") == "true",
                            "enabled": attrs.get("enabled") == "true",
                        })
                    if len(nodes) >= 100:
                        break
                return {"elements": nodes, "truncated": len(nodes) >= 100}
            except ET.ParseError as exc:
                raise AndroidError("invalid_ui_tree") from exc
            finally:
                try:
                    self.adb(serial, "shell", "rm", "-f", path)
                except AndroidError:
                    pass
        if name == "capture":
            raw = self.adb(serial, "exec-out", "screencap", "-p", timeout=7)
            if len(raw) > MAX_RAW_IMAGE or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise AndroidError("invalid_screenshot")
            jpeg = self._call([
                FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error",
                "-f", "image2pipe", "-vcodec", "png", "-i", "pipe:0",
                "-vf", "scale=480:-2", "-frames:v", "1",
                "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "10", "pipe:1",
            ], timeout=5, data=raw)
            if not jpeg.startswith(b"\xff\xd8") or not 0 < len(jpeg) <= MAX_IMAGE:
                raise AndroidError("image_limit_exceeded")
            return {"content": [{"type": "image", "mimeType": "image/jpeg",
                                 "data": base64.b64encode(jpeg).decode("ascii")}]}
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


def call_tool(name, arguments, *, device=None):
    device = device or Device()
    try:
        result = device.invoke(name, arguments)
        if name == "capture":
            return result
        return {"content": [{"type": "text", "text": json.dumps(result, separators=(",", ":"))}]}
    except (AndroidError, ValueError) as exc:
        code = str(exc) if isinstance(exc, AndroidError) else "invalid_arguments"
        return {"content": [{"type": "text", "text": json.dumps({"error": code})}], "isError": True}


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
        return call_tool(params.get("name"), params.get("arguments", {}), device=device)
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
