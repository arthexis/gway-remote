"""Constrained, opt-in physical USB Android canary acceptance on gway-001.

This is a local node-owned consumer, NOT an exposed MCP ADB/shell interface.
Only manual Android Canary GitHub Actions artifacts for an allowlisted PR.
Never install, uninstall, or launch the production application package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone

REPO = "arthexis/gway-remote"
WORKFLOW = "android-canary.yml"
APP = "com.arthexis.gwayremote.canary"
TEST = APP + ".test"
PRODUCTION = "com.arthexis.gwayremote"
RUNNER = "androidx.test.runner.AndroidJUnitRunner"
SUITE = ",".join((
    "com.arthexis.gwayremote.ModuleNavigationComposeTest",
    "com.arthexis.gwayremote.ModulePageComposeTest",
    "com.arthexis.gwayremote.AppearanceThemeTest",
))
# Explicit named suites only; never accept arbitrary instrumentation classes.
SUITES = {
    "baseline": (SUITE, 6),
    "quotations": ("com.arthexis.gwayremote.OdooQuotationRefreshTest", 5),
    "opportunities": ("com.arthexis.gwayremote.OdooOpportunityCopyTest", 2),
}
FILES = ("gway-remote-canary.apk", "gway-remote-canary-test.apk")
SHA = re.compile(r"[0-9a-f]{40}\Z")


class CanaryError(RuntimeError):
    pass


def command(args, *, timeout=30):
    """Fixed argv, no shell; exceptions deliberately exclude subprocess output."""
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CanaryError("command_unavailable_or_timeout") from exc
    if result.returncode:
        raise CanaryError("command_failed")
    return result.stdout


def gh(path):
    return json.loads(command(["gh", "api", path], timeout=25))


def provenance(directory, *, pr, sha, run_id):
    """Verify both APK hashes, exact trusted workflow provenance and file shape."""
    directory = Path(directory)
    names = set(FILES) | {"PROVENANCE.txt", "SHA256SUMS"}
    if not directory.is_dir() or {p.name for p in directory.iterdir()} != names:
        raise CanaryError("unexpected_artifact_files")
    for name in names:
        p = directory / name
        if p.is_symlink() or not p.is_file() or p.stat().st_size > 120_000_000:
            raise CanaryError("unsafe_artifact_file")
    if not SHA.fullmatch(sha):
        raise CanaryError("invalid_source_sha")
    fields = {}
    for line in (directory / "PROVENANCE.txt").read_text().splitlines():
        if ": " not in line:
            raise CanaryError("invalid_provenance")
        k, v = line.split(": ", 1)
        if k in fields:
            raise CanaryError("duplicate_provenance")
        fields[k] = v
    expected = {
        "Repository": REPO, "Pull-Request": str(pr), "Source-Commit": sha,
        "Actions-Run": str(run_id), "Canary-Overlay": "package-and-label-v1",
        "Package": APP, "Test-Package": TEST, "Test-Runner": RUNNER,
        "Signing": "ephemeral Android debug certificate",
    }
    if fields != expected:
        raise CanaryError("provenance_mismatch")
    lines = (directory / "SHA256SUMS").read_text().splitlines()
    hashes = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([\w.-]+)", line)
        if not match or match.group(2) in hashes:
            raise CanaryError("invalid_checksum_manifest")
        hashes[match.group(2)] = match.group(1)
    if set(hashes) != set(FILES):
        raise CanaryError("checksum_file_set_mismatch")
    for name in FILES:
        p = directory / name
        if not p.stat().st_size:
            raise CanaryError("empty_apk")
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if digest != hashes[name]:
            raise CanaryError("apk_digest_mismatch")
    return hashes


def eligible_run(pr, expected_run=None):
    """Only a successful manual workflow run whose artifact matches current PR HEAD."""
    item = gh(f"repos/{REPO}/pulls/{pr}")
    if item.get("state") != "open" or item.get("head", {}).get("repo", {}).get("full_name") != REPO:
        raise CanaryError("pr_not_allowlisted_open_source")
    sha = item.get("head", {}).get("sha", "")
    if not SHA.fullmatch(sha):
        raise CanaryError("invalid_pr_sha")
    payload = gh(f"repos/{REPO}/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&per_page=20")
    for run in payload.get("workflow_runs", []):
        if (run.get("event") != "workflow_dispatch" or run.get("head_branch") != "main"
                or run.get("status") != "completed" or run.get("conclusion") != "success"):
            continue
        run_id = run.get("id")
        if type(run_id) is not int or (expected_run is not None and run_id != expected_run):
            continue
        listing = gh(f"repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=25")
        name = f"android-canary-pr{pr}-{sha[:12]}"
        for artifact in listing.get("artifacts", []):
            if (artifact.get("name") == name and not artifact.get("expired")
                    and artifact.get("workflow_run", {}).get("id") == run_id):
                return run_id, name, sha
    raise CanaryError("no_verified_canary_for_current_pr_head")


def usb():
    output = command(["adb", "devices", "-l"], timeout=10)
    lines = [line.strip().split() for line in output.splitlines()[1:] if line.strip()]
    if len(lines) != 1 or len(lines[0]) < 3 or lines[0][1] != "device":
        raise CanaryError("usb_not_unique_authorized")
    serial = lines[0][0]
    if ":" in serial or serial.startswith("emulator-") or not any(
        part.startswith("usb:") for part in lines[0][2:]
    ):
        raise CanaryError("non_usb_device_denied")
    if command(["adb", "-s", serial, "shell", "getprop", "ro.kernel.qemu"], timeout=8).strip() == "1":
        raise CanaryError("emulator_denied")
    return serial


def adb(serial, *args, timeout=25):
    return command(["adb", "-s", serial, *args], timeout=timeout)


def device_ready(serial, *, wake=False):
    power = adb(serial, "shell", "dumpsys", "power", timeout=10)
    was_awake = bool(re.search(r"mWakefulness=Awake|mWakefulness=AWAKE", power))
    if not was_awake and wake:
        adb(serial, "shell", "input", "keyevent", "224", timeout=10)
        time.sleep(1)
        power = adb(serial, "shell", "dumpsys", "power", timeout=10)
    if not re.search(r"mWakefulness=Awake|mWakefulness=AWAKE", power):
        raise CanaryError("screen_not_awake")
    window = adb(serial, "shell", "dumpsys", "window", timeout=15)
    # Require an explicit unlocked signal. Unknown = deny, never auto-unlock.
    if re.search(r"(?:mShowingLockscreen|mKeyguardShowing|isStatusBarKeyguard)=true", window):
        raise CanaryError("screen_locked")
    if not re.search(r"(?:mShowingLockscreen|mKeyguardShowing|isStatusBarKeyguard)=false", window):
        raise CanaryError("lock_state_unknown")
    return was_awake


def install(serial, directory, *, allow_canary_reset=False):
    before = adb(serial, "shell", "pm", "path", PRODUCTION)
    for name, package in zip(FILES, (APP, TEST)):
        apath = str(Path(directory) / name)
        args = ["adb", "-s", serial, "install", "-r", apath]
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=100)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CanaryError("canary_install_timeout_or_unavailable") from exc
        if result.returncode or "Success" not in result.stdout:
            # Only a *known* canary package signature/version conflict can reset.
            diagnostic = result.stdout + result.stderr
            known_conflict = ("INSTALL_FAILED_UPDATE_INCOMPATIBLE" in diagnostic
                              or "INSTALL_FAILED_VERSION_DOWNGRADE" in diagnostic)
            if not (allow_canary_reset and known_conflict):
                raise CanaryError("canary_install_failed_no_reset")
            if not adb(serial, "shell", "pm", "path", package).startswith("package:"):
                raise CanaryError("canary_package_not_found_for_reset")
            adb(serial, "uninstall", package, timeout=30)
            if "Success" not in command(args, timeout=100):
                raise CanaryError("canary_install_unconfirmed")
    after = adb(serial, "shell", "pm", "path", PRODUCTION)
    if after != before:
        raise CanaryError("production_package_changed")
    if not adb(serial, "shell", "pm", "path", APP).startswith("package:"):
        raise CanaryError("canary_package_missing")
    if not adb(serial, "shell", "pm", "path", TEST).startswith("package:"):
        raise CanaryError("test_package_missing")


@contextmanager
def keep_usb_screen_on(serial):
    """Temporarily prevent USB screen timeout during physical instrumentation.

    Preserve the exact old Android global setting, including an absent key.
    Fail closed if USB power cannot be confirmed; restore even on test failure.
    No persistent screen, network, or production-app changes.
    """
    key = "stay_on_while_plugged_in"
    battery = adb(serial, "shell", "dumpsys", "battery", timeout=10)
    if not re.search(r"(?mi)^\s*USB powered:\s*true\s*$", battery):
        raise CanaryError("usb_power_unconfirmed")
    original = adb(serial, "shell", "settings", "get", "global", key, timeout=10).strip()
    if original == "null":
        old = 0
    elif re.fullmatch(r"[0-9]{1,2}", original) and 0 <= int(original) <= 15:
        old = int(original)
    else:
        raise CanaryError("usb_stayon_unknown_initial_setting")
    target = old | 2  # BatteryManager.BATTERY_PLUGGED_USB
    changed = target != old
    try:
        if changed:
            adb(serial, "shell", "settings", "put", "global", key, str(target), timeout=10)
            readback = adb(serial, "shell", "settings", "get", "global", key, timeout=10).strip()
            if readback != str(target):
                raise CanaryError("usb_stayon_set_unconfirmed")
        yield
    finally:
        if changed:
            try:
                if original == "null":
                    adb(serial, "shell", "settings", "delete", "global", key, timeout=10)
                    restored = adb(serial, "shell", "settings", "get", "global", key, timeout=10).strip()
                    valid = restored == "null"
                else:
                    adb(serial, "shell", "settings", "put", "global", key, original, timeout=10)
                    restored = adb(serial, "shell", "settings", "get", "global", key, timeout=10).strip()
                    valid = restored == original
            except CanaryError as exc:
                raise CanaryError("usb_stayon_restore_failed") from exc
            if not valid:
                raise CanaryError("usb_stayon_restore_unconfirmed")


def instrument(serial, *, wake=False, suite="baseline"):
    if suite not in SUITES:
        raise CanaryError("unknown_test_suite")
    classes, minimum = SUITES[suite]
    try:
        with keep_usb_screen_on(serial):
            # Screen could sleep between post-install preflight and guard activation.
            # Recheck *after* USB wake protection is active; never unlock.
            device_ready(serial, wake=wake)
            result = adb(
                serial, "shell", "am", "instrument", "-w", "-r", "-e", "class", classes,
                f"{TEST}/{RUNNER}", timeout=180
            )
        m = re.search(r"OK \((\d+) tests?\)", result)
        if "INSTRUMENTATION_CODE: -1" not in result or not m or int(m.group(1)) < minimum:
            raise CanaryError("instrumentation_failed")
        return int(m.group(1))
    finally:
        # Canaries only; no credentials, screenshots or production force-stop.
        for package in (APP, TEST):
            try:
                adb(serial, "shell", "am", "force-stop", package, timeout=10)
            except CanaryError:
                pass


def state_path(suite="baseline"):
    if suite not in SUITES:
        raise CanaryError("unknown_test_suite")
    filename = "android-canary.json" if suite == "baseline" else f"android-canary-{suite}.json"
    return Path.home() / ".local/state/gway-remote" / filename


def write_state(path, record):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, sort_keys=True) + "\n")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def run(pr, *, install_enabled=False, reset=False, wake=False, retry=False, suite="baseline", expected_run=None):
    if suite not in SUITES:
        raise CanaryError("unknown_test_suite")
    if not 1 <= pr <= 9999999:
        raise CanaryError("invalid_pr_number")
    run_id, artifact, sha = eligible_run(pr) if expected_run is None else eligible_run(pr, expected_run)
    state_file = state_path(suite)
    if state_file.exists():
        old = json.loads(state_file.read_text())
        if old.get("run_id") == run_id and old.get("suite", "baseline") == suite and not retry:
            return {"status": "already_attempted", "run_id": run_id, "source_sha": sha, "suite": suite}
    # No permanent SDK or Java on 001: gh downloads a CI-built paired artifact.
    with tempfile.TemporaryDirectory(prefix="gway-canary-") as directory:
        command(["gh", "run", "download", str(run_id), "-R", REPO,
                 "--name", artifact, "--dir", directory], timeout=70)
        provenance(directory, pr=pr, sha=sha, run_id=run_id)
        if not install_enabled:
            return {"status": "verified_only", "run_id": run_id, "source_sha": sha, "suite": suite}
        serial = usb()
        was_awake = device_ready(serial, wake=wake)
        record = {
            "run_id": run_id, "source_sha": sha, "pr": pr, "suite": suite, "status": "failed",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            before_production = adb(serial, "shell", "pm", "path", PRODUCTION)
            install(serial, directory, allow_canary_reset=reset)
            # Package installation can consume the display timeout. Revalidate
            # a live unlocked screen before starting the Compose runner.
            device_ready(serial, wake=wake)
            record["tests_passed"] = instrument(serial, wake=wake, suite=suite)
            if adb(serial, "shell", "pm", "path", PRODUCTION) != before_production:
                raise CanaryError("production_package_changed")
            record["production_package_unchanged"] = True
            record["status"] = "passed"
        except CanaryError as exc:
            record["reason"] = str(exc)
            raise
        finally:
            if wake and not was_awake:
                try:
                    adb(serial, "shell", "input", "keyevent", "223", timeout=10)
                except CanaryError:
                    pass
            write_state(state_file, record)
        return record


def main():
    parser = argparse.ArgumentParser(description="Bounded gway-001 USB canary consumer")
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--install", action="store_true", help="explicit opt-in physical test")
    parser.add_argument("--allow-canary-reset", action="store_true", help="only isolated canary package")
    parser.add_argument("--wake", action="store_true", help="restore screen-off after test")
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--expected-run", type=int)
    parser.add_argument("--suite", choices=tuple(SUITES), default="baseline")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.pr, install_enabled=args.install,
                             reset=args.allow_canary_reset, wake=args.wake,
                             retry=args.retry, suite=args.suite, expected_run=args.expected_run), sort_keys=True))
    except (CanaryError, OSError, ValueError, json.JSONDecodeError) as exc:
        # Never include command stdout/stderr, device serials, private UI or tokens.
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
