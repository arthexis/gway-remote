"""Hermetic tests of semantic Android targeting and settled UI conditions."""
import unittest

from gway_remote.android_ui_harness import (
    UiTargetError, check, point, poll,
)
from gway_remote.mcp_android import Device, TOOLS, call_tool, handle_rpc
from gway_remote.mcp_tool_scope import required_scope


def node(uid="com.example:id/open", *, bounds="[100,200][200,300]",
         enabled=True, clickable=True, **flags):
    return {
        "resource_id": uid, "bounds": bounds,
        "enabled": enabled, "clickable": clickable,
        **flags,
    }


def tree(*items, truncated=False):
    return {"elements": list(items), "truncated": truncated}


class FakeDevice(Device):
    """No ADB process or real USB access is ever attempted."""
    def __init__(self, snapshots, *, screen_on=True, locked=False, rotation=0,
                 wake_succeeds=True):
        self.snapshots = list(snapshots)
        self.actions = []
        self.wake_succeeds = wake_succeeds
        self.states = []
        self.base_state = {"screen_on": screen_on, "locked": locked,
                           "rotation": rotation}

    def serial(self):
        return "fake-single-usb"

    def size(self, serial):
        return (1080, 2220)

    def screen_state(self, serial):
        if self.states:
            return self.states.pop(0)
        return dict(self.base_state)

    def ui_tree(self, serial):
        if not self.snapshots:
            raise UiTargetError("no_ui_snapshot")
        return self.snapshots.pop(0)

    def adb(self, serial, *args, timeout=6):
        self.actions.append(args)
        if args == ("shell", "input", "keyevent", "KEYCODE_WAKEUP") and self.wake_succeeds:
            self.base_state["screen_on"] = True
        return b""


class SemanticContracts(unittest.TestCase):
    def test_exact_id_requires_unique_untruncated_clickable_and_valid_bounds(self):
        a = node()
        self.assertEqual(point(tree(a), a["resource_id"], width=1080, height=2220),
                         (150, 250))
        for sample in (
            tree(a, a),
            tree(a, truncated=True),
            tree(node(enabled=False)),
            tree(node(clickable=False)),
            tree(node(bounds="[-1,2][3,4]")),
            tree(node(bounds="[100,100][1081,200]")),
            tree(node(bounds="[300,200][200,300]")),
            tree(node(uid="other")),
        ):
            with self.subTest(sample=sample), self.assertRaises(UiTargetError):
                point(sample, a["resource_id"], width=1080, height=2220)

    def test_no_fuzzy_selector_or_absence_from_partial_snapshot(self):
        for value in ("/../../etc", "a*","", "a"*121, "x;rm"):
            with self.subTest(value=value), self.assertRaises(UiTargetError):
                point(tree(node()), value, width=1080, height=2220)
        with self.assertRaises(UiTargetError):
            check(tree(node(), truncated=True), "another:id/button", "absent")
        self.assertTrue(check(tree(node()), "another:id/button", "absent"))
        self.assertFalse(check(tree(node()), "another:id/button", "present"))

    def test_wait_is_bounded_and_has_no_action_retry(self):
        states = iter([
            tree(node(checked=False)),
            tree(node(checked=True)),
        ])
        pauses = []
        result = poll(lambda: next(states), resource_id="com.example:id/open",
                      state="checked", wait=400, pause=pauses.append)
        self.assertEqual(result, {"status": "confirmed", "attempts": 2})
        self.assertEqual(pauses, [0.4])
        self.assertEqual(poll(lambda: tree(), resource_id="a:id/b",
                              state="present", wait=0),
                         {"status": "timeout", "attempts": 1})
        with self.assertRaises(UiTargetError):
            poll(lambda: tree(), resource_id="a:id/b",
                 state="present", wait=10000)

    def test_semantic_touch_checks_preconditions_and_rechecks_state(self):
        uid = "com.example:id/open"
        dev = FakeDevice([tree(node(uid))])
        result = dev.invoke("tap_target", {"resource_id": uid})
        self.assertEqual(result["verification"], "unverified")
        self.assertEqual(dev.actions, [("shell", "input", "tap", 150, 250)])

        woke = FakeDevice([tree(node(uid))], screen_on=False)
        accepted = woke.invoke("tap_target", {"resource_id": uid})
        self.assertEqual(accepted["wake_invocations"], 1)
        self.assertEqual(woke.actions, [
            ("shell", "input", "keyevent", "KEYCODE_WAKEUP"),
            ("shell", "input", "tap", 150, 250),
        ])

        for kwargs in (
            {"locked": True},
            {"locked": None},
            {"rotation": None},
        ):
            with self.subTest(kwargs=kwargs):
                device = FakeDevice([tree(node(uid))], **kwargs)
                with self.assertRaisesRegex(ValueError, "screen_not_safe"):
                    device.invoke("tap_target", {"resource_id": uid})
                self.assertEqual(device.actions, [])

        # A failed/uncertain wake never dispatches a tap or repeats WAKEUP.
        failed = FakeDevice([tree(node(uid))], screen_on=False, wake_succeeds=False)
        with self.assertRaisesRegex(ValueError, "screen_not_ready"):
            failed.invoke("tap_target", {"resource_id": uid})
        self.assertEqual(failed.actions,
                         [("shell", "input", "keyevent", "KEYCODE_WAKEUP")])
        unknown = FakeDevice([tree(node(uid))], screen_on=None)
        with self.assertRaisesRegex(ValueError, "screen_state_unknown"):
            unknown.invoke("tap_target", {"resource_id": uid})
        self.assertEqual(unknown.actions, [])
        locked = FakeDevice([tree(node(uid))], screen_on=False, locked=True)
        with self.assertRaisesRegex(ValueError, "screen_not_safe"):
            locked.invoke("tap_target", {"resource_id": uid})
        self.assertEqual(locked.actions,
                         [("shell", "input", "keyevent", "KEYCODE_WAKEUP")])

        device = FakeDevice([tree(node(uid))])
        device.states = [
            {"screen_on": True, "locked": False, "rotation": 0},
            {"screen_on": True, "locked": False, "rotation": 90},
        ]
        with self.assertRaises(ValueError):
            device.invoke("tap_target", {"resource_id": uid})
        self.assertEqual(device.actions, [])

    def test_tap_and_wait_prove_change_without_repeating_tap(self):
        uid = "com.example:id/open"
        target = "com.example:id/panel"
        device = FakeDevice([tree(node(uid)), tree(node(uid), node(target))])
        result = device.invoke("tap_target", {
            "resource_id": uid, "expect_id": target,
            "expect_state": "present", "wait_ms": 0,
        })
        self.assertEqual(result["verification"], "confirmed")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(len(device.actions), 1)

    def test_read_wait_cannot_touch(self):
        uid = "com.example:id/checkbox"
        device = FakeDevice([tree(node(uid, checked=True))])
        self.assertEqual(device.invoke("wait_ui", {
            "resource_id": uid, "state": "checked",
        }), {"status": "confirmed", "attempts": 1})
        self.assertEqual(device.actions, [])
        device = FakeDevice([], screen_on=False)
        self.assertEqual(device.invoke("wait_ui", {
            "resource_id": uid, "state": "present",
        }), {"status": "unknown", "attempts": 0})
        self.assertEqual(device.actions, [])

    def test_mcp_scopes_and_strict_args(self):
        self.assertEqual({t["name"] for t in TOOLS} & {"tap_target", "wait_ui"},
                         {"tap_target", "wait_ui"})
        scopes = {t["name"]: required_scope(t) for t in TOOLS}
        self.assertEqual(scopes["tap_target"], "execute")
        self.assertEqual(scopes["wait_ui"], "read")
        self.assertEqual(len(TOOLS), 15)
        self.assertEqual(len(handle_rpc({"jsonrpc":"2.0","id":1,
                                         "method":"tools/list","params":{}})["tools"]), 15)
        invalid = (
            {"resource_id": "abc", "expect_id": "def"},
            {"resource_id": "abc", "expect_state": "present"},
            {"resource_id": "abc", "wait_ms": True},
            {"resource_id": "abc", "wait_ms": 801},
            {"resource_id": "abc", "path": "/etc/passwd"},
        )
        for args in invalid:
            with self.subTest(args=args):
                result = call_tool("tap_target", args, device=FakeDevice([]))
                self.assertTrue(result["isError"])


if __name__ == "__main__":
    unittest.main()
