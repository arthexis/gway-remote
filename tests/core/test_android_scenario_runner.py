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
    def __init__(self, *, authorized=True, screen_on=True, locked=False,
                 wake_succeeds=True):
        self.calls = []
        self.wake_succeeds = wake_succeeds
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

    def wake_if_needed(self):
        self.calls.append(("wake_if_needed", {}))
        state = self.state
        if state["screen_on"] is None:
            raise ValueError("screen_state_unknown")
        woke = state["screen_on"] is False
        if woke and not self.wake_succeeds:
            raise ValueError("screen_not_ready")
        if woke:
            state["screen_on"] = True
        if state["locked"] is not False:
            raise ValueError("screen_not_safe")
        return {"ok": True, "woke": woke}


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
        self.assertEqual(result["action_invocations"], 0)
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
        self.assertEqual(result["action_invocations"], 0)
        self.assertEqual(dev.calls, [("status", {})])

    def test_reviewed_navigation_succeeds_only_when_screen_safe(self):
        dev = FakeDevice()
        receipt = runner.run("home-screen-stability-v1",
                             device=dev, receipt_root=self.root)
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["action_invocations"], 1)
        self.assertEqual([x[0] for x in dev.calls], ["status", "key", "status"])
        self.assertEqual(dev.calls[1], ("key", {"key": "HOME"}))
        unsafe = FakeDevice(screen_on=False)
        receipt = runner.run("home-screen-stability-v1",
                             device=unsafe, receipt_root=self.root)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual([x[0] for x in unsafe.calls], ["status"])

    def test_home_stability_v2_wakes_only_when_needed_and_preserves_v1(self):
        old = runner.preview("home-screen-stability-v1")
        self.assertEqual(old["step_types"], ["status", "key", "status"])
        self.assertEqual(old["actions"], 1)
        v2 = runner.preview("home-screen-stability-v2")
        self.assertEqual(v2["step_types"],
                         ["status", "wake_if_needed", "status", "key", "status"])
        self.assertEqual(v2["actions"], 2)
        self.assertNotEqual(v2["spec_sha256"], old["spec_sha256"])

        asleep = FakeDevice(screen_on=False)
        result = runner.run("home-screen-stability-v2", device=asleep,
                            receipt_root=self.root)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["action_invocations"], 2)
        self.assertEqual([x[0] for x in asleep.calls],
                         ["status", "wake_if_needed", "status", "key", "status"])
        receipt = runner.result(result["receipt_id"], root=self.root)
        self.assertEqual(receipt["sha256"], result["receipt_sha256"])
        self.assertEqual(receipt["manifest"]["action_invocations"], 2)
        self.assertEqual(receipt["manifest"]["screenshots"], "not_collected")
        self.assertNotIn("password", json.dumps(receipt["manifest"]))
        self.assertEqual(runner.preview("home-screen-stability-v1")["spec_sha256"],
                         old["spec_sha256"])

        awake = FakeDevice()
        result = runner.run("home-screen-stability-v2", device=awake,
                            receipt_root=self.root)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["action_invocations"], 1)

    def test_v2_rejects_unsafe_states_without_home_or_retry(self):
        for dev in (FakeDevice(authorized=False, screen_on=False),
                    FakeDevice(screen_on=None), FakeDevice(screen_on=False,
                                                          wake_succeeds=False),
                    FakeDevice(screen_on=False, locked=True),
                    FakeDevice(screen_on=True, locked=True)):
            with self.subTest(state=dev.state):
                result = runner.run("home-screen-stability-v2", device=dev,
                                    receipt_root=self.root)
                self.assertEqual(result["status"], "failed")
                self.assertFalse(any(name == "key" for name, _ in dev.calls))
                self.assertLessEqual(sum(name == "wake_if_needed" for name, _ in dev.calls), 1)

    def test_semantic_scenario_is_bounded_and_stops_on_uncertainty(self):
        class Semantic(FakeDevice):
            def semantic_transition(self, source, destination):
                self.calls.append((source, destination))
                return next(self.outcomes)
        preview = runner.preview("developer-options-from-search-v1")
        self.assertEqual(preview["actions"], 2)
        self.assertEqual(preview["run_scope"], "gway:execute")
        for outcomes, expected, count in [
            ([{"status": "confirmed", "dispatched": True}] * 2, "passed", 2),
            ([{"status": "unconfirmed", "dispatched": True}], "failed", 1),
            ([{"status": "unconfirmed", "dispatched": False}], "failed", 0),
        ]:
            dev = Semantic()
            dev.outcomes = iter(outcomes)
            receipt = runner.run("developer-options-from-search-v1", device=dev,
                                 receipt_root=self.root)
            self.assertEqual(receipt["status"], expected)
            self.assertEqual(receipt["action_invocations"], count)
            self.assertEqual(len(dev.calls), 2 if expected == "passed" else 1)

    def test_semantic_receipt_dispatch_attribution_is_sanitized_and_consistent(self):
        class Semantic(FakeDevice):
            def semantic_transition(self, source, destination):
                self.calls.append((source, destination))
                if isinstance(self.observed, Exception):
                    raise self.observed
                return self.observed
        for observed, count, dispatch, reason in [
            ({"status": "unconfirmed", "dispatched": False, "reason": "target_changed"},
             0, "not_attempted", "target_changed"),
            ({"status": "unconfirmed", "dispatched": True, "reason": "dispatch_uncertain"},
             1, "uncertain", "dispatch_uncertain"),
            ({"status": "unconfirmed", "dispatched": True, "reason": "verification_error"},
             1, "attempted", "verification_error"),
            ({"status": "confirmed", "dispatched": False, "reason": "private text"},
             0, "not_attempted", None),
            (TimeoutError("private text"), 1, "uncertain", "provider_error"),
        ]:
            with self.subTest(dispatch=dispatch, reason=reason):
                dev = Semantic()
                dev.observed = observed
                receipt = runner.run("developer-options-from-search-v1", device=dev,
                                     receipt_root=self.root)
                verified = runner.result(receipt["receipt_id"], root=self.root)
                self.assertEqual(verified["sha256"], receipt["receipt_sha256"])
                self.assertEqual(receipt["status"], "failed")
                self.assertEqual(receipt["action_invocations"], count)
                self.assertEqual(verified["manifest"]["action_invocations"], count)
                trace = verified["manifest"]["operations"][0]
                self.assertEqual(trace["dispatch"], dispatch)
                self.assertEqual(trace.get("reason"), reason)
                self.assertNotIn("private text", json.dumps(verified))
                self.assertEqual(len(dev.calls), 1)

    def test_explicit_read_execute_scope_and_strict_scenario_ids(self):
        scopes = {t["name"]: required_scope(t) for t in TOOLS}
        self.assertEqual(scopes["scenario_preview"], "read")
        self.assertEqual(scopes["scenario_run"], "execute")
        self.assertEqual(scopes["scenario_result"], "read")
        self.assertEqual(scopes["scenario_status"], "read")
        self.assertEqual(scopes["scenario_reconcile"], "execute")
        self.assertEqual(scopes["navigation_model"], "read")
        self.assertEqual(len(TOOLS), 15)
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
