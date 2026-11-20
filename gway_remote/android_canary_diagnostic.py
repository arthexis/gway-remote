"""Sanitized physical USB Compose instrumentation diagnostic (opt-in only).

Does not install packages, alter production, store screenshots, print raw UI,
report device serial or publish raw AndroidJUnitRunner output.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from gway_remote import android_canary_field as field


def summarize(raw: str) -> dict:
    """Extract only fixed-schema counts and allowlisted test identities."""
    codes = [int(x) for x in re.findall(r"^INSTRUMENTATION_STATUS_CODE:\s*(-?\d+)\s*$", raw, re.M)]
    seen = []
    cls = test = None
    for line in raw.splitlines():
        if line.startswith("INSTRUMENTATION_STATUS: class="):
            cls = line.partition("=")[2].strip()
        elif line.startswith("INSTRUMENTATION_STATUS: test="):
            test = line.partition("=")[2].strip()
        elif line.startswith("INSTRUMENTATION_STATUS_CODE:"):
            match = re.fullmatch(r"INSTRUMENTATION_STATUS_CODE:\s*(-?\d+)", line)
            if match and int(match.group(1)) == -2:
                if cls in field.SUITE.split(",") and test and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,100}", test):
                    seen.append(f"{cls.rsplit('.',1)[-1]}.{test}")
                else:
                    seen.append("unidentified_test_failure")
    footer = re.search(r"OK \((\d+) tests?\)", raw)
    failure_summary = re.search(r"Tests run:\s*(\d+),\s*Failures:\s*(\d+)", raw)
    result = re.search(r"^INSTRUMENTATION_CODE:\s*(-?\d+)\s*$", raw, re.M)
    return {
        "footer_ok": footer is not None,
        "footer_test_count": int(footer.group(1)) if footer else None,
        "footer_failures": (int(failure_summary.group(2)) if failure_summary else None),
        "instrumentation_code": int(result.group(1)) if result else None,
        "started": codes.count(1),
        "passed_status": codes.count(0),
        "failed_status": codes.count(-2),
        "other_status_codes": sorted(set(codes) - {0, 1, -2}),
        "failed_tests": sorted(set(seen))[:12],
    }


def main():
    serial = field.usb()
    was_awake = field.device_ready(serial, wake=True)
    try:
        for pkg in (field.APP, field.TEST):
            if not field.adb(serial, "shell", "pm", "path", pkg).startswith("package:"):
                raise field.CanaryError("required_canary_package_missing")
        result = field.adb(
            serial, "shell", "am", "instrument", "-w", "-r", "-e", "class",
            field.SUITE, f"{field.TEST}/{field.RUNNER}", timeout=180
        )
        safe = summarize(result)
        p = Path.home() / ".local/state/gway-remote/android-canary-diagnostic.json"
        field.write_state(p, safe)
        print(json.dumps(safe, sort_keys=True))
    except field.CanaryError as e:
        print(json.dumps({"status": "blocked", "reason": str(e)}))
        raise SystemExit(1)
    finally:
        for package in (field.APP, field.TEST):
            try:
                field.adb(serial, "shell", "am", "force-stop", package, timeout=10)
            except field.CanaryError:
                pass
        if not was_awake:
            try:
                field.adb(serial, "shell", "input", "keyevent", "223", timeout=10)
            except field.CanaryError:
                pass


if __name__ == "__main__":
    main()
