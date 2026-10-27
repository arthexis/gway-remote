"""Fail-closed inspection using an operator-approved registry and Bastion SSH profile.

The registry file must be provisioned over an authenticated administrative channel.
This module never enrolls hosts, accepts SSH host keys, or modifies remote services.
"""
from __future__ import annotations

import json
import os
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
    # Address is returned for diagnostic correlation only. SSH must use the
    # Bastion-owned alias with pinned host key and approved ProxyJump.
    result = inspect_ssh(node, runner=runner) if runner is not None else inspect_ssh(node)
    return {"node": node, "management_address": address, "registry": "verified-local-file",
            "ssh": result["ssh"], "inspection": "read-only",
            "note": "SSH probe only; installed revisions not verified remotely"}
