"""Hermetic tests of approved Android scenarios and private receipt storage."""
import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote import android_scenario_runner as runner
from gway_remote.mcp_android import TOOLS, call_tool
from gway_remote.mcp_tool_scope import required_scope


class FakeDevice:
    def __init__(self, *, authorized=True, screen_on=True, locked=False):
        self.calls = []
        self.state = {"usb": "authorized" if authorized else "unauthorized",
                      "screen_on": screen_on, "locked": locked}

    def invoke(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "status":
            return dict(self.state)
        if name == "key":
            return {"ok": True, "action": name}
        if name == "tap_target":
            return {"ok": True, "verification": "confirmed"}
        if name == "wait_ui":
            return {"status": "confirmed"}
        raise ValueError("bad operation")


class ScenarioContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "receipts"
        self.root.mkdir(mode=0o700)

    def test_preview_is_immutable_bounded_and_no_secrets(self):
        p = runner.preview("usb-readiness-v1")
        self.assertEqual(p["actions"], 0)
        self.assertEqual(p["execution"], "not_started")
        self.assertEqual(p["step_types"], ["status"])
        self.assertEqual(len(p["spec_sha256"]), 64)
        with self.assertRaises(runner.ScenarioError):
            runner.preview("../script.py")
        self.assertEqual(runner.preview("usb-readiness-v1")["spec_sha256"],
                         p["spec_sha256"])

    def test_readonly_scenario_receipt_private_and_hashed(self):
        dev = FakeDevice()
        result = runner.run("usb-readiness-v1", device=dev, receipt_root=self.root)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["actions_dispatched"], 0)
        self.assertEqual(dev.calls, [("status", {})])
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        name = result["receipt_id"] + ".json"
        path = self.root / name
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        data = path.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         result["receipt_sha256"])
        receipt = runner.result(result["receipt_id"], root=self.root)
        self.assertEqual(receipt["manifest"]["status"], "passed")
        self.assertEqual(receipt["manifest"]["screenshots"], "not_collected")
        self.assertNotIn("serial", data.decode())
        self.assertNotIn("text", data.decode())
        self.assertNotIn("password", data.decode())

    def test_failed_readiness_does_not_interact(self):
        dev = FakeDevice(authorized=False)
        result = runner.run("usb-readiness-v1", device=dev, receipt_root=self.root)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["actions_dispatched"], 0)
        self.assertEqual(dev.calls, [("status", {})])

    def test_reviewed_navigation_succeeds_only_when_screen_safe(self):
        dev = FakeDevice()
        receipt = runner.run("home-screen-stability-v1",
                             device=dev, receipt_root=self.root)
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["actions_dispatched"], 1)
        self.assertEqual([x[0] for x in dev.calls], ["status", "key", "status"])
        self.assertEqual(dev.calls[1], ("key", {"key": "HOME"}))
        unsafe = FakeDevice(screen_on=False)
        receipt = runner.run("home-screen-stability-v1",
                             device=unsafe, receipt_root=self.root)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual([x[0] for x in unsafe.calls], ["status"])

    def test_explicit_read_execute_scope_and_strict_scenario_ids(self):
        scopes = {t["name"]: required_scope(t) for t in TOOLS}
        self.assertEqual(scopes["scenario_preview"], "read")
        self.assertEqual(scopes["scenario_run"], "execute")
        self.assertEqual(scopes["scenario_result"], "read")
        self.assertEqual(len(TOOLS), 12)
        for name in ("scenario_preview", "scenario_run"):
            with self.subTest(name=name):
                err = call_tool(name, {"scenario_id": "../../etc/passwd"},
                                device=FakeDevice())
                self.assertTrue(err["isError"])
        bad = call_tool("scenario_run", {
            "scenario_id": "usb-readiness-v1", "steps": ["adb shell rm"]},
            device=FakeDevice())
        self.assertTrue(bad["isError"])

    def test_bad_receipt_id_or_symlink_does_not_escape_private_storage(self):
        for value in ("../etc", "/etc/passwd", "f" * 31,
                      "z" * 32):
            with self.subTest(value=value), self.assertRaises(
                    runner.ScenarioError):
                runner.result(value, root=self.root)
        escaped = self.root / ("a" * 32 + ".json")
        escaped.symlink_to(Path(self.temp.name) / "secret")
        with self.assertRaises(runner.ScenarioError):
            runner.result("a" * 32, root=self.root)

    def test_storage_limit_is_checked_before_any_device_action(self):
        with patch.object(runner, "_MAX_RECEIPTS", 0):
            dev = FakeDevice()
            with self.assertRaisesRegex(runner.ScenarioError, "receipt_storage_full"):
                runner.run("usb-readiness-v1", device=dev, receipt_root=self.root)
            self.assertEqual(dev.calls, [])

    def test_scenario_does_not_persist_private_ui_result(self):
        class Leaky(FakeDevice):
            def invoke(self, name, arguments):
                x = super().invoke(name, arguments)
                x["private_token"] = "secret-not-for-receipts"
                return x
        receipt = runner.run("usb-readiness-v1",
                             device=Leaky(), receipt_root=self.root)
        content = (self.root / (receipt["receipt_id"] + ".json")).read_text()
        self.assertNotIn("private_token", content)
        self.assertNotIn("secret-not-for-receipts", content)


if __name__ == "__main__":
    unittest.main()
