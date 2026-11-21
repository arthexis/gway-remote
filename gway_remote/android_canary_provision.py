"""One-shot, USB-only, no-plaintext-output canary Mobile API credential provisioner.

Runs on the node that physically owns Android USB. No MCP generic ADB endpoint,
no Watchtower shell, no production Android package, and no token in arguments.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

from . import android_canary_field as field
from .mobile_device_tokens import DeviceCredentials

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


def pipe_to_canary(serial, credential):
    # Only ADB stdin carries secret bytes; command arguments, stderr, stdout,
    # GitHub artifacts and MCP replies never contain the bearer.
    if not credential.startswith("gwymob1_") or len(credential) > 110:
        raise ProvisionError("invalid_mobile_device_credential")
    command = [
        "adb", "-s", serial, "exec-in", "run-as", field.APP,
        "sh", "-c", f"umask 077; test -d files && cat > {PROVISION_FILE}",
    ]
    try:
        result = subprocess.run(
            command, input=credential.encode("ascii"), capture_output=True, timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProvisionError("private_usb_handoff_unavailable") from None
    if result.returncode:
        raise ProvisionError("private_usb_handoff_failed")


def run(*, pr, sha, run_id, directory):
    # Verify downloaded artifacts before touching Android or minting credentials.
    validate_artifact(pr=pr, sha=sha, run_id=run_id, directory=directory)
    registry = DeviceCredentials()
    serial = field.usb()
    record = None
    was_awake = False
    initialized = False
    try:
        was_awake = field.device_ready(serial, wake=True)
        initialized = True
        with field.keep_usb_screen_on(serial):
            field.install(serial, directory, allow_canary_reset=True)
            field.device_ready(serial, wake=True)
            record = registry.issue(label=LABEL, scope="read", days=30)
            pipe_to_canary(serial, record["token"])
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
            compose = field.instrument(serial, wake=True)
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
        raise ProvisionError("usb_mobile_provisioning_failed") from None
    finally:
        try:
            field.adb(serial, "shell", "run-as", field.APP, "rm", "-f", PROVISION_FILE, timeout=8)
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
    args = parser.parse_args()
    try:
        print(json.dumps(run(pr=args.pr, sha=args.sha, run_id=args.run_id,
                             directory=args.artifact_dir), sort_keys=True))
    except (field.CanaryError, ProvisionError, ValueError, OSError):
        print(json.dumps({"status": "blocked", "reason": "canary_provision_unverified"}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
