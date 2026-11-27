"""One-shot, USB-only, no-plaintext-output canary Mobile API credential provisioner.

Runs on the node that physically owns Android USB. No MCP generic ADB endpoint,
no Watchtower shell, no production Android package, and no token in arguments.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path
import re
import subprocess

from . import android_canary_field as field
from .mobile_device_tokens import DeviceCredentials, TOKEN

LABEL = "gway-001-usb-canary"
PROVISION_TEST = "com.arthexis.gwayremote.MobileDeviceProvisionTest"
PROVISION_FILE = "files/.gway-mobile-token-once"


class ProvisionError(RuntimeError):
    pass


def validate_artifact(*, pr, sha, run_id, directory):
    if not field.SHA.fullmatch(sha) or type(run_id) is not int or run_id <= 0:
        raise ProvisionError("invalid_source_identity")
    request = field.gh(f"repos/{field.REPO}/pulls/{pr}")
    head = request.get("head") or {}
    # A reviewed artifact is normally built while its source PR is open.
    # After a successful merge that same immutable artifact remains eligible.
    state_ok = request.get("state") == "open" or (
        request.get("state") == "closed" and request.get("merged") is True
    )
    if (not state_ok
            or head.get("sha") != sha
            or (head.get("repo") or {}).get("full_name") != field.REPO):
        raise ProvisionError("source_pr_changed_or_untrusted")
    run = field.gh(f"repos/{field.REPO}/actions/runs/{run_id}")
    if (run.get("event") != "workflow_dispatch" or run.get("status") != "completed"
            or run.get("conclusion") != "success" or run.get("head_branch") != "main"
            or not str(run.get("path", "")).endswith("/android-canary.yml")):
        raise ProvisionError("manual_canary_run_not_accepted")
    artifact_name = f"android-canary-pr{pr}-{sha[:12]}"
    listing = field.gh(f"repos/{field.REPO}/actions/runs/{run_id}/artifacts?per_page=25")
    matching = [a for a in listing.get("artifacts", [])
                if a.get("name") == artifact_name and not a.get("expired")
                and (a.get("workflow_run") or {}).get("id") == run_id]
    if len(matching) != 1:
        raise ProvisionError("approved_paired_artifact_missing")
    field.provenance(directory, pr=pr, sha=sha, run_id=run_id)


def _private_command(serial, *args):
    """Only fixed, private run-as commands; output never carries a token."""
    try:
        return subprocess.run(
            ["adb", "-s", serial, "exec-out", "run-as", field.APP, *args],
            capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ProvisionError("private_usb_command_unavailable") from None


def pipe_to_canary(serial, credential):
    """One-way ADB stdin, integrity-verified within the canary sandbox.

    On the gway-001 Samsung Android 8 device, adb exec-in can return zero
    without delivering bytes to run-as. The verified compatible duplex
    transport is adb shell -T. Host exit codes alone are never acceptance.
    """
    if type(credential) is not str or not TOKEN.fullmatch(credential):
        raise ProvisionError("invalid_mobile_device_credential")
    secret_bytes = credential.encode("ascii")
    expected = hashlib.sha256(secret_bytes).hexdigest()
    try:
        # A clean canary reinstall may not have created files/ yet.
        _private_command(serial, "mkdir", "-p", "files")
        _private_command(serial, "chmod", "700", "files")
        directory = _private_command(serial, "ls", "-ld", "files")
        words = directory.stdout.decode("utf-8", errors="replace").split()
        if directory.returncode or not words or words[0] != "drwx------":
            raise ProvisionError("private_usb_directory_unverified")
        written = subprocess.run(
            ["adb", "-s", serial, "shell", "-T", "run-as", field.APP,
             "dd", "of=" + PROVISION_FILE, "bs=128"],
            input=secret_bytes, capture_output=True, timeout=15, check=False,
        )
        if written.returncode:
            raise ProvisionError("private_usb_write_failed")
        _private_command(serial, "chmod", "600", PROVISION_FILE)
        digest_result = _private_command(serial, "sha256sum", PROVISION_FILE)
        parts = digest_result.stdout.decode("ascii", errors="replace").split()
        if (digest_result.returncode or not parts
                or not re.fullmatch(r"[0-9a-f]{64}", parts[0])
                or not hmac.compare_digest(parts[0], expected)):
            raise ProvisionError("private_usb_checksum_unconfirmed")
        mode_result = _private_command(serial, "ls", "-l", PROVISION_FILE)
        modes = mode_result.stdout.decode("utf-8", errors="replace").split()
        if mode_result.returncode or not modes or modes[0] != "-rw-------":
            raise ProvisionError("private_usb_mode_unconfirmed")
    except (ProvisionError, OSError, subprocess.TimeoutExpired):
        try:
            _private_command(serial, "rm", "-f", PROVISION_FILE)
        except ProvisionError:
            pass
        raise ProvisionError("private_usb_handoff_unverified") from None



def verify_installed_pair(serial, directory):
    """Require byte-for-byte identity of both installed, unsplit canary APKs.

    Only the two fixed canary packages are inspected; no production mutation.
    Unrecognized paths, split APKs or digest output fail closed.
    """
    for name, package in zip(field.FILES, (field.APP, field.TEST)):
        source = Path(directory) / name
        expected = hashlib.sha256(source.read_bytes()).hexdigest()
        paths = field.adb(serial, "shell", "pm", "path", package, timeout=10).splitlines()
        if len(paths) != 1:
            raise ProvisionError("installed_canary_path_unverified")
        match = re.fullmatch(r"package:(/data/app/[A-Za-z0-9_./=+-]+/base\.apk)", paths[0].strip())
        if not match or any(part in (".", "..") for part in match[1].split("/")):
            raise ProvisionError("installed_canary_path_unverified")
        digest = field.adb(serial, "shell", "sha256sum", match[1], timeout=30).strip()
        actual = re.fullmatch(r"([0-9a-f]{64})\s+" + re.escape(match[1]), digest)
        if not actual or not hmac.compare_digest(actual[1], expected):
            raise ProvisionError("installed_canary_digest_mismatch")


def run(*, pr, sha, run_id, directory, verified_installed=False):
    # Verify downloaded artifacts before touching Android or minting credentials.
    validate_artifact(pr=pr, sha=sha, run_id=run_id, directory=directory)
    registry = DeviceCredentials()
    serial = field.usb()
    record = None
    was_awake = False
    initialized = False
    stage = "usb_power_guard"
    try:
        with field.keep_usb_screen_on(serial):
            stage = "device_ready"
            was_awake = field.device_ready(serial, wake=True)
            initialized = True
            if verified_installed:
                stage = "installed_pair_verification"
                verify_installed_pair(serial, directory)
            else:
                stage = "paired_install"
                field.install(serial, directory, allow_canary_reset=True)
            stage = "post_install_ready"
            field.device_ready(serial, wake=True)
            stage = "credential_issue"
            record = registry.issue(label=LABEL, scope="read", days=30)
            stage = "private_handoff"
            pipe_to_canary(serial, record["token"])
            stage = "android_https"
            # Instrumentation itself consumes/delete the private seed and probes
            # the real HTTPS endpoint with the imported AndroidKeystore bearer.
            result = field.adb(
                serial, "shell", "am", "instrument", "-w", "-r",
                "-e", "gway_usb_provision", "v1", "-e", "class",
                PROVISION_TEST, f"{field.TEST}/{field.RUNNER}", timeout=100,
            )
            if ("OK (1 test)" not in result
                    or "INSTRUMENTATION_CODE: -1" not in result
                    or "FAILURES" in result):
                raise ProvisionError("android_https_authentication_failed")
            stage = "baseline_compose"
            compose = field.instrument(serial, wake=True)
            stage = "power_restore"
            return {
                "status": "passed", "label": LABEL, "credential_id": record["id"],
                "scope": record["scope"], "expires_at": record["expires_at"],
                "android_https": "verified", "compose_tests_passed": compose,
                "source_sha": sha, "run_id": run_id,
            }
    except Exception:
        if record is not None:
            try:
                registry.revoke(record["id"])
            except Exception:
                pass
        raise ProvisionError("usb_mobile_provisioning_failed:" + stage) from None
    finally:
        try:
            _private_command(serial, "rm", "-f", PROVISION_FILE)
        except Exception:
            pass
        if initialized and not was_awake:
            try:
                field.adb(serial, "shell", "input", "keyevent", "223", timeout=10)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="USB canary-only Mobile API enrollment")
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--sha", type=str, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--verified-installed", action="store_true",
                        help="require matching installed canary and test APK hashes; do not reinstall")
    args = parser.parse_args()
    try:
        print(json.dumps(run(pr=args.pr, sha=args.sha, run_id=args.run_id,
                             directory=args.artifact_dir,
                             verified_installed=args.verified_installed), sort_keys=True))
    except (field.CanaryError, ProvisionError, ValueError, OSError) as exc:
        stages = ("usb_power_guard", "device_ready", "paired_install", "installed_pair_verification", "post_install_ready",
                  "credential_issue", "private_handoff", "android_https", "baseline_compose", "power_restore")
        allowed = {"usb_mobile_provisioning_failed:" + stage for stage in stages}
        reason = str(exc) if isinstance(exc, ProvisionError) and str(exc) in allowed else "canary_provision_unverified"
        print(json.dumps({"status": "blocked", "reason": reason}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
