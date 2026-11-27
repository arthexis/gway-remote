"""Hermetic Android MCP provider contracts: no connected phone or node required."""
import base64
import json
import subprocess
import unittest

from gway_remote.mcp_android import AndroidError, Device, TOOLS, call_tool, handle_rpc
from gway_remote.mcp_gateway_federation import federated_tool_result
from gway_remote.mcp_tool_scope import required_scope


class FakeRun:
    def __init__(self, devices=None):
        self.devices = devices or (
            b"List of devices attached\nSERIAL123 device usb:1-1.4 model:SM_G950F\n")
        self.commands = []
        self.size = b"Physical size: 1440x2960\nOverride size: 1080x2220\n"

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        if argv[0].endswith("ffmpeg"):
            data = b"\xff\xd8" + b"a" * 60
        elif argv[-2:] == [ "devices", "-l" ]:
            data = self.devices
        elif argv[-3:] == ["shell", "wm", "size"]:
            data = self.size
        elif argv[-3:] == ["shell", "getprop", "ro.product.model"]:
            data = b"SM-G950F\n"
        elif argv[-3:] == ["shell", "dumpsys", "power"]:
            data = b"mWakefulness=Awake\nDisplay Power: state=ON\n"
        elif argv[-3:] == ["shell", "dumpsys", "trust"]:
            data = b"User (current): trusted=0, deviceLocked=0\n"
        elif argv[-3:] == ["shell", "dumpsys", "input"]:
            data = b"SurfaceOrientation: 1\n"
        elif argv[-3:] == ["exec-out", "screencap", "-p"]:
            data = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
                    + (1080).to_bytes(4, "big") + (2220).to_bytes(4, "big")
                    + b"a" * 10)
        elif argv[-3:] == ["shell", "cat", "/sdcard/.gway-remote-ui.xml"]:
            data = (b'<hierarchy><node text="Visible" clickable="true" '
                    b'enabled="true" bounds="[0,0][100,100]" />'
                    b'<node text="secret" password="true" /></hierarchy>')
        else:
            data = b""
        return subprocess.CompletedProcess(argv, 0, data, b"")


class DeviceContracts(unittest.TestCase):
    def test_single_usb_device_and_redacted_status(self):
        runner = FakeRun()
        result = Device(runner).invoke("status", {})
        self.assertEqual(result["model"], "SM-G950F")
        self.assertEqual((result["width"], result["height"]), (1080, 2220))
        self.assertEqual((result["screen_on"], result["locked"], result["rotation"]),
                         (True, False, 90))
        self.assertNotIn("SERIAL123", json.dumps(result))

    def test_unknown_screen_state_is_null_not_guessed(self):
        class UnknownDump(FakeRun):
            def __call__(self, argv, **kwargs):
                if "dumpsys" in argv:
                    return subprocess.CompletedProcess(argv, 1, b"", b"denied")
                return super().__call__(argv, **kwargs)
        result = Device(UnknownDump()).invoke("status", {})
        self.assertEqual((result["screen_on"], result["locked"], result["rotation"]),
                         (None, None, None))
        self.assertEqual(result["usb"], "authorized")

    def test_ambiguous_or_network_device_never_runs_action(self):
        for devices in (
            b"List of devices attached\nA device usb:1-1\nB device usb:1-2\n",
            b"List of devices attached\nA unauthorized usb:1-1\n",
            b"List of devices attached\nA device product:remote\n",
        ):
            with self.subTest(devices=devices):
                runner = FakeRun(devices)
                with self.assertRaises(AndroidError):
                    Device(runner).invoke("key", {"key": "BACK"})
                self.assertEqual(len(runner.commands), 1)

    def test_reject_bad_arguments_before_adb_invocation(self):
        for tool, args in (
            ("tap", {"x": True, "y": 2}),
            ("swipe", {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "duration_ms": 2000}),
            ("key", {"key": "POWER"}),
            ("text", {"value": "pass; rm -rf /"}),
            ("status", {"serial": "untrusted"}),
        ):
            with self.subTest(tool=tool):
                runner = FakeRun()
                result = call_tool(tool, args, device=Device(runner))
                self.assertTrue(result["isError"])
                self.assertEqual(runner.commands, [])

    def test_screen_bounds_fail_before_touch(self):
        runner = FakeRun()
        with self.assertRaisesRegex(AndroidError, "coordinate_out_of_bounds"):
            Device(runner).invoke("tap", {"x": 1080, "y": 22})
        self.assertFalse(any("input" in cmd for cmd in runner.commands))

    def test_tap_swipe_key_and_text_use_argv_not_shell(self):
        runner = FakeRun()
        device = Device(runner)
        device.invoke("tap", {"x": 100, "y": 200})
        device.invoke("swipe", {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "duration_ms": 200})
        device.invoke("key", {"key": "BACK"})
        device.invoke("text", {"value": "hello world"})
        self.assertTrue(any(cmd[-4:] == ["input", "tap", "100", "200"] for cmd in runner.commands))
        self.assertTrue(any(cmd[-3:] == ["input", "keyevent", "KEYCODE_BACK"] for cmd in runner.commands))
        self.assertTrue(any(cmd[-3:] == ["input", "text", "hello%sworld"] for cmd in runner.commands))
        self.assertFalse(any(cmd[0].endswith("sh") for cmd in runner.commands))

    def test_ui_redacts_password_and_cleans_up(self):
        runner = FakeRun()
        result = Device(runner).invoke("ui_tree", {})
        self.assertEqual(result["elements"][0]["text"], "Visible")
        self.assertEqual({key: result["elements"][0][key]
                          for key in ("checked", "selected", "focused", "scrollable")},
                         {"checked": False, "selected": False, "focused": False,
                          "scrollable": False})
        self.assertNotIn("secret", json.dumps(result))
        self.assertTrue(any(cmd[-3:] == ["rm", "-f", "/sdcard/.gway-remote-ui.xml"]
                            for cmd in runner.commands))

    def test_bounded_image_is_mcp_image_not_json_text(self):
        runner = FakeRun()
        result = call_tool("capture", {}, device=Device(runner))
        self.assertEqual(result["content"][0]["type"], "image")
        self.assertEqual(base64.b64decode(result["content"][0]["data"])[:2], b"\xff\xd8")
        meta = result["structuredContent"]
        self.assertEqual((meta["native_width"], meta["native_height"]), (1080, 2220))
        self.assertEqual((meta["capture_width"], meta["capture_height"]), (480, 986))
        self.assertEqual(meta["scale_x"], 2.25)
        self.assertAlmostEqual(meta["scale_y"], 2220 / 986)
        self.assertEqual(federated_tool_result(result), result)
        self.assertEqual(len(result["content"]), 1)
        self.assertTrue(any("scale=480:986" in cmd for cmd in runner.commands))

    def test_invalid_png_dimensions_fail_before_ffmpeg(self):
        class BadPng(FakeRun):
            def __call__(self, argv, **kwargs):
                if argv[-3:] == ["exec-out", "screencap", "-p"]:
                    return subprocess.CompletedProcess(argv, 0, b"\x89PNG\r\n\x1a\n" + b"a" * 10, b"")
                return super().__call__(argv, **kwargs)
        runner = BadPng()
        self.assertTrue(call_tool("capture", {}, device=Device(runner))["isError"])
        self.assertFalse(any(cmd[0].endswith("ffmpeg") for cmd in runner.commands))

    def test_reject_oversized_image(self):
        class HugeRun(FakeRun):
            def __call__(self, argv, **kwargs):
                if argv[0].endswith("ffmpeg"):
                    return subprocess.CompletedProcess(argv, 0, b"\xff\xd8" + b"x" * 140_001, b"")
                return super().__call__(argv, **kwargs)
        result = call_tool("capture", {}, device=Device(HugeRun()))
        self.assertTrue(result["isError"])
        self.assertIn("image_limit_exceeded", result["content"][0]["text"])


class McpProtocolContracts(unittest.TestCase):
    def test_tools_scopes_use_existing_mcp_annotations(self):
        scopes = {tool["name"]: required_scope(tool) for tool in TOOLS}
        self.assertEqual(scopes["status"], "read")
        self.assertEqual(scopes["ui_tree"], "read")
        self.assertEqual(scopes["capture"], "read")
        for action in ("tap", "swipe", "key", "text"):
            self.assertEqual(scopes[action], "execute")

    def test_standard_stdio_mcp_contract(self):
        init = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(init["protocolVersion"], "2025-03-26")
        tools = handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        self.assertEqual(len(tools["tools"]), 15)
        self.assertIsNone(handle_rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_legacy_provider_results_are_unchanged(self):
        original = {"content": [{"type": "text", "text": '{"ok":true}'}]}
        result = federated_tool_result(original)
        self.assertEqual(json.loads(result["content"][0]["text"]), original)

    def test_valid_image_survives_federated_gateway(self):
        jpeg = b"\xff\xd8jpeg"
        result = {"content": [{"type": "image", "mimeType": "image/jpeg",
                               "data": base64.b64encode(jpeg).decode()}]}
        self.assertEqual(federated_tool_result(result), result)

    def test_image_metadata_cannot_carry_arbitrary_fields(self):
        image = {"type": "image", "mimeType": "image/jpeg",
                 "data": base64.b64encode(b"\xff\xd8jpeg").decode()}
        for metadata in (
            {"arbitrary": "secret"},
            {"native_width": 1080, "native_height": 2220, "capture_width": 480,
             "capture_height": 986, "scale_x": True, "scale_y": 2220 / 986},
            {"native_width": 1080, "native_height": 2220, "capture_width": 480,
             "capture_height": 986, "scale_x": 3.0, "scale_y": 2220 / 986},
        ):
            with self.subTest(metadata=metadata):
                with self.assertRaises(ValueError):
                    federated_tool_result({"content": [image], "structuredContent": metadata})

    def test_bad_provider_image_fails_closed(self):
        for result in (
            {"content": [{"type": "image", "mimeType": "image/png", "data": "AA=="}]},
            {"content": [{"type": "image", "mimeType": "image/jpeg", "data": "not-base64!!!"}]},
            {"content": [{"type": "image", "mimeType": "image/jpeg", "data": "AA=="},
                         {"type": "text", "text": "extra"}]},
        ):
            with self.subTest(result=result):
                with self.assertRaises(ValueError):
                    federated_tool_result(result)


if __name__ == "__main__":
    unittest.main()
