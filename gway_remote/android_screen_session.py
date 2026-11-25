"""Bounded, managed physical USB screen-awake window for interactive acceptance.

Only the approved manual workflow invokes this module on gway-001.
No APK operations, credentials, app launches, or generic command input.
"""
import argparse
import json
import signal
import threading
import time

from . import android_canary_field as field
from .mcp_android import Device

DURATIONS = (120, 180, 300)


def session(seconds, *, stop, emit, clock=time.monotonic):
    if type(seconds) is not int or seconds not in DURATIONS:
        raise field.CanaryError("invalid_session_duration")
    serial = field.usb()
    initial = Device().screen_state(serial)
    if initial.get("locked") is not False or initial.get("screen_on") not in (True, False):
        raise field.CanaryError("screen_not_safe")
    key = "stay_on_while_plugged_in"
    previous = field.adb(serial, "shell", "settings", "get", "global", key, timeout=10).strip()
    try:
        with field.keep_usb_screen_on(serial):
            field.device_ready(serial, wake=True)
            deadline = clock() + seconds
            emit({"status": "ready", "duration_seconds": seconds})
            stop.wait(max(0, deadline - clock()))
    finally:
        if initial["screen_on"] is False:
            field.adb(serial, "shell", "input", "keyevent", "223", timeout=10)
    restored = field.adb(serial, "shell", "settings", "get", "global", key, timeout=10).strip()
    if restored != previous:
        raise field.CanaryError("screen_setting_restore_unconfirmed")
    return {"status": "cancelled" if stop.is_set() else "passed",
            "power_setting_restored": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, choices=DURATIONS, required=True)
    args = parser.parse_args()
    stop = threading.Event()
    # Cooperative cancellation permits the existing guard's finally to run.
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    def emit(value):
        print(json.dumps(value, sort_keys=True), flush=True)
    try:
        emit(session(args.seconds, stop=stop, emit=emit))
    except (field.CanaryError, OSError, ValueError):
        emit({"status": "blocked", "reason": "screen_session_failed"})
        raise SystemExit(1)


if __name__ == "__main__":
    main()
