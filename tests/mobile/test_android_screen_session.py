import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from gway_remote import android_screen_session as session


class ScreenSessionTests(unittest.TestCase):
    def test_bounded_and_restored(self):
        events = []
        @contextmanager
        def guard(serial):
            events.append("set")
            try:
                yield
            finally:
                events.append("restore")
        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.side_effect = lambda duration: events.append(duration)
        with patch.object(session.field, "usb", return_value="test"), \
             patch.object(session.Device, "screen_state", return_value={"locked": False, "screen_on": False}), \
             patch.object(session.field, "adb", return_value="null") as adb, \
             patch.object(session.field, "keep_usb_screen_on", side_effect=guard), \
             patch.object(session.field, "device_ready") as ready:
            result = session.session(120, stop=stop, emit=lambda v: events.append(v["status"]), clock=lambda: 0)
        self.assertEqual(events, ["set", "ready", 120, "restore"])
        self.assertEqual(result, {"status": "passed", "power_setting_restored": True})
        ready.assert_called_once_with("test", wake=True)
        adb.assert_any_call("test", "shell", "input", "keyevent", "223", timeout=10)

    def test_locked_denied(self):
        with patch.object(session.field, "usb", return_value="test"), \
             patch.object(session.Device, "screen_state", return_value={"locked": True, "screen_on": True}), \
             patch.object(session.field, "keep_usb_screen_on") as guard:
            with self.assertRaises(session.field.CanaryError):
                session.session(120, stop=Mock(), emit=Mock())
            guard.assert_not_called()

    def test_failure_unwinds_guard(self):
        restored = []
        @contextmanager
        def guard(serial):
            try:
                yield
            finally:
                restored.append(True)
        with patch.object(session.field, "usb", return_value="test"), \
             patch.object(session.Device, "screen_state", return_value={"locked": False, "screen_on": True}), \
             patch.object(session.field, "adb", return_value="0"), \
             patch.object(session.field, "keep_usb_screen_on", side_effect=guard), \
             patch.object(session.field, "device_ready", side_effect=session.field.CanaryError("not_awake")):
            with self.assertRaises(session.field.CanaryError):
                session.session(120, stop=Mock(), emit=Mock())
        self.assertEqual(restored, [True])

    def test_reject_unbounded(self):
        for value in (True, 0, 301, "120"):
            with self.assertRaises(session.field.CanaryError):
                session.session(value, stop=Mock(), emit=Mock())
