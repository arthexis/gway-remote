"""Fail-closed inspection using an operator-approved registry and Bastion SSH profile.

The registry file must be provisioned over an authenticated administrative channel.
This module never enrolls hosts, accepts SSH host keys, or modifies remote services.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .node_inspection import inspect_ssh, resolve_target

REGISTRY = Path("/etc/gway-remote/watchtower-inspection.json")
SSH_CONFIG = Path("/etc/gway-remote/inspection-ssh.conf")


def inspect(node, *, approved, registry_path=REGISTRY, ssh_config=SSH_CONFIG, runner=None):
    if node not in approved:
        raise ValueError("inspection target not approved")
    from .watchtower_inspection_client import fetch_snapshot
    snapshot = fetch_snapshot(config=ssh_config)
    address = resolve_target(snapshot, node, approved)
    config = Path(ssh_config)
    if not config.is_file() or config.is_symlink() or config.stat().st_mode & 0o022:
        raise ValueError("trusted SSH configuration unavailable")
    if config.stat().st_uid != os.geteuid():
        raise ValueError("SSH config owner mismatch")
    # Verify Bastion's effective SSH destination matches the trusted registry.
    # An alias pointing at a different host must not pass as this node.
    try:
        effective = subprocess.run(
            ["ssh", "-F", str(config), "-G", node],
            capture_output=True, text=True, check=True, timeout=8,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError("SSH target configuration unavailable") from exc
    options = dict(line.split(None, 1) for line in effective.splitlines() if " " in line)
    if options.get("hostname") != address or options.get("stricthostkeychecking", "").lower() != "yes":
        raise ValueError("SSH target does not match trusted registry identity")
    if options.get("batchmode", "").lower() != "yes":
        raise ValueError("SSH profile must use BatchMode")
    if options.get("userknownhostsfile") in (None, "/dev/null"):
        raise ValueError("SSH host trust unavailable")
    # Bastion owns host keys and ProxyJump; never auto-enroll them.
    result = inspect_ssh(node, config=config, runner=runner) if runner is not None else inspect_ssh(node, config=config)
    evidence = {"state": "unknown", "components": []}
    if result["ssh"] == "verified":
        try:
            command = ["ssh", "-F", str(config), "-o", "BatchMode=yes",
                       "-o", "StrictHostKeyChecking=yes", node,
                       "gway-remote", "status", "--json"]
            proc = subprocess.run(command, capture_output=True, text=True, timeout=25, check=True)
            if len(proc.stdout) > 131072:
                raise ValueError("remote status too large")
            report = json.loads(proc.stdout)
            if report.get("schema") != "gway-remote/status/v1" or not isinstance(report.get("components"), list):
                raise ValueError("invalid remote status")
            evidence = {"state": "reported", "components": [
                {"name": row.get("name"), "installed_sha": row.get("installed_sha"),
                 "health": row.get("health")}
                for row in report["components"] if isinstance(row, dict)
            ]}
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, TypeError):
            pass
    return {"node": node, "management_address": address, "registry": "authenticated-watchtower-ssh", "remote_evidence": evidence,
            "ssh": result["ssh"], "inspection": "read-only",
            "note": "Remote status evidence is reported, not independently verified; missing status remains unknown"}
