#!/usr/bin/env python3
"""Opt-in gway-001 field regression: exercise the forced-command sudo transition.

Run as root *on the node after provisioning*, not in CI. It uses the exact
gway-relay -> gway-exec restricted sudo command, without SSH or a shell.
The SSH key / Match policy must be verified separately by the field agent.
"""
import json
import os
import secrets
import subprocess
import sys
import time

PROTOCOL = [
    "/usr/bin/sudo", "-n", "-u", "gway-relay",
    "/usr/bin/sudo", "-n", "-u", "gway-exec",
    "/usr/bin/env", "PYTHONPATH=/opt/gway-remote",
    "/usr/bin/python3", "-m", "gway_remote.node_exec_protocol",
]


def call(message):
    result = subprocess.run(
        PROTOCOL, input=json.dumps(message), capture_output=True,
        text=True, timeout=20, check=False,
    )
    if result.returncode:
        raise RuntimeError("restricted protocol rejected test request")
    response = json.loads(result.stdout)
    if response.get("error"):
        raise RuntimeError("restricted protocol denied test request")
    return response


def main():
    if os.geteuid() != 0 or os.uname().nodename != "gway-001":
        raise SystemExit("run as root on gway-001 only")
    rid = secrets.token_hex(16)
    common = {"node": "gway-001", "request_id": rid}
    accepted = call(dict(common, operation="submit", command="hostname"))
    if accepted.get("status") != "accepted":
        raise AssertionError("hostname was not accepted")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = call(dict(common, operation="result", cursor=0))
        if result["status"] in ("succeeded", "failed", "cancelled", "unknown", "timed_out"):
            if result["status"] != "succeeded" or result["stdout"].strip() != "gway-001":
                raise AssertionError("worker failed: " + repr({
                    "status": result["status"], "diagnostic": result["stderr"],
                    "exit_code": result["exit_code"]}))
            print("PASS: fixed sudo transition -> user bus -> systemd transient job -> result")
            return
        time.sleep(0.25)
    raise TimeoutError("job did not reach terminal state")


if __name__ == "__main__":
    sys.exit(main())
