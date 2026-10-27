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
    # An absent or untrusted registry must never trigger hostname/IP guessing.
    path = Path(registry_path)
    stat = path.lstat()
    if not path.is_file() or path.is_symlink() or stat.st_mode & 0o022:
        raise ValueError("untrusted registry permissions")
    if stat.st_uid != os.geteuid():
        raise ValueError("registry owner mismatch")
    if stat.st_size > 65536:
        raise ValueError("registry too large")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
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
    return {"node": node, "management_address": address, "registry": "verified-local-file",
            "ssh": result["ssh"], "inspection": "read-only",
            "note": "SSH probe only; installed revisions not verified remotely"}
