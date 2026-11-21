"""Manual, canary-only USB installer. The workflow validates artifact provenance first.

This module does not download artifacts or run instrumentation. A signature reset
requires an explicit operator-selected workflow input and discards canary data.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

CANARY = "com.arthexis.gwayremote.canary"
PRODUCTION = "com.arthexis.gwayremote"
SIGNATURE_CONFLICT = "INSTALL_FAILED_UPDATE_INCOMPATIBLE"


class InstallBlocked(RuntimeError):
    pass


def run_command(argv, timeout=40):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InstallBlocked("adb_unavailable_or_timeout") from exc


def require_success(result, error):
    if result.returncode != 0:
        raise InstallBlocked(error)
    return result.stdout.strip()


def authorized_usb(call=run_command):
    result = call(["/usr/bin/adb", "devices", "-l"], 10)
    output = require_success(result, "usb_discovery_failed")
    rows = [line.split() for line in output.splitlines()[1:] if line.strip()]
    if len(rows) != 1 or len(rows[0]) < 3:
        raise InstallBlocked("usb_not_unique")
    serial, status, *details = rows[0]
    if (status != "device" or ":" in serial or serial.startswith("emulator-")
            or not any(item.startswith("usb:") for item in details)):
        raise InstallBlocked("usb_not_authorized_physical")
    result = call(["/usr/bin/adb", "-s", serial, "shell", "getprop", "ro.kernel.qemu"], 10)
    if require_success(result, "device_check_failed") == "1":
        raise InstallBlocked("emulator_denied")
    return serial


def install(apk: str, *, reset_allowed: bool = False, call=run_command):
    file = Path(apk)
    if not file.is_file() or file.is_symlink() or not (10_000 < file.stat().st_size < 104_857_600):
        raise InstallBlocked("invalid_verified_apk_path")
    serial = authorized_usb(call)

    def adb(*args, timeout=30):
        return call(["/usr/bin/adb", "-s", serial, *args], timeout)

    def package_path(package):
        return require_success(adb("shell", "pm", "path", package), "package_inspection_failed")

    before = package_path(PRODUCTION)
    outcome = None
    try:
        first = adb("install", "-r", str(file), timeout=100)
        if first.returncode == 0 and first.stdout.strip() == "Success":
            outcome = "updated"
        else:
            output = first.stdout + first.stderr
            conflict = re.search(
                r"Failure \[INSTALL_FAILED_UPDATE_INCOMPATIBLE(?::|\])", output
            ) is not None
            if not reset_allowed or not conflict:
                raise InstallBlocked("canary_install_rejected_no_reset")
            existing = package_path(CANARY)
            if not existing.startswith("package:") or not all(
                line.startswith("package:") for line in existing.splitlines()
            ):
                raise InstallBlocked("canary_not_installed_for_reset")
            if before != package_path(PRODUCTION):
                raise InstallBlocked("production_path_changed")
            removed = adb("uninstall", CANARY, timeout=45)
            if removed.returncode != 0 or removed.stdout.strip() != "Success":
                raise InstallBlocked("canary_reset_failed")
            if package_path(CANARY):
                raise InstallBlocked("canary_reset_not_confirmed")
            second = adb("install", "-r", str(file), timeout=100)
            if second.returncode != 0 or second.stdout.strip() != "Success":
                raise InstallBlocked("canary_reinstall_failed")
            outcome = "canary_reset_and_installed"
        if not package_path(CANARY).startswith("package:"):
            raise InstallBlocked("canary_install_not_confirmed")
    finally:
        if package_path(PRODUCTION) != before:
            raise InstallBlocked("production_path_changed")
    return outcome


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", required=True)
    parser.add_argument("--reset-canary", action="store_true")
    args = parser.parse_args()
    try:
        print("Canary installation: " + install(args.apk, reset_allowed=args.reset_canary))
    except InstallBlocked as exc:
        parser.exit(1, "Canary installation blocked: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
