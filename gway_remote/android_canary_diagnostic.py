"""Sanitized physical USB Compose instrumentation diagnostic (opt-in only).

Does not alter production, store screenshots, print raw UI,
report device serial or publish raw AndroidJUnitRunner output.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
from pathlib import Path

if __package__:
    from . import android_canary_field as field
else:
    import android_canary_field as field


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
    types = sorted(set(re.findall(
        r"\b(?:java|androidx|kotlin|android)\.[A-Za-z0-9_.$]+(?:Exception|Error)\b", raw
    )))[:8]

    # Only framework/test-class identifiers from stack frames; no messages,
    # app logs, parameter values, serial numbers or original stack strings.
    # Tolerate runner prefixes and source-less Android stack frames.
    frame_pattern = re.compile(
        r"\bat\s+((?:androidx\.(?:compose|test)\.|com\.arthexis\.gwayremote\.|java\.lang\.)"
        r"[A-Za-z0-9_.$]{1,180})\("
    )
    frames = list(dict.fromkeys(frame_pattern.findall(raw)))[:14]
    categories = {
        "no_compose_roots": "No compose hierarchies found",
        "activity_not_launched": "Activity was not set",
        "activity_scenario": "ActivityScenario",
        "ui_not_idle": "idle",
        "content_already_set": "already set content",
    }
    category = next((key for key, needle in categories.items()
                     if needle.lower() in raw.lower()), "other_illegal_state")
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
        "exception_types": types,
        "allowlisted_stack_frames": frames,
        "illegal_state_category": category,
    }


def main():
    parser = argparse.ArgumentParser(description="Sanitized USB canary instrumentation")
    parser.add_argument("--reinstall-pr", type=int, choices=(644,),
                        help="reproduce immediate post-install tests for approved PR 644 only")
    parser.add_argument("--settle-seconds", type=int, choices=(0, 15), default=0,
                        help="bounded post-install Android initialization interval")
    parser.add_argument("--test-timeout", type=int, choices=(25, 180), default=180,
                        help="bounded instrumentation timeout for short remote executor")
    args = parser.parse_args()
    serial = field.usb()
    was_awake = field.device_ready(serial, wake=True)
    try:
        if args.reinstall_pr is not None:
            run_id, artifact, sha = field.eligible_run(args.reinstall_pr)
            with tempfile.TemporaryDirectory(prefix="gway-canary-probe-") as directory:
                field.command(["gh", "run", "download", str(run_id), "-R", field.REPO,
                               "--name", artifact, "--dir", directory], timeout=70)
                field.provenance(directory, pr=args.reinstall_pr, sha=sha, run_id=run_id)
                field.install(serial, directory, allow_canary_reset=False)
            field.device_ready(serial, wake=True)
            if args.settle_seconds:
                time.sleep(args.settle_seconds)
        for pkg in (field.APP, field.TEST):
            if not field.adb(serial, "shell", "pm", "path", pkg).startswith("package:"):
                raise field.CanaryError("required_canary_package_missing")
        with field.keep_usb_screen_on(serial):
            result = field.adb(
                serial, "shell", "am", "instrument", "-w", "-r", "-e", "class",
                field.SUITE, f"{field.TEST}/{field.RUNNER}", timeout=args.test_timeout
            )
        safe = summarize(result)
        safe["post_install"] = args.reinstall_pr is not None
        safe["settle_seconds"] = args.settle_seconds
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
