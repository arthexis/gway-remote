"""Fail-closed inspection using a restricted Watchtower export and Bastion SSH.

This module never enrolls hosts, accepts SSH host keys, or modifies remote services.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .node_inspection import inspect_ssh, resolve_target

SSH_CONFIG = Path("/etc/gway-remote/inspection-ssh.conf")


def inspect(node, *, approved, ssh_config=SSH_CONFIG, runner=None):
    if node not in approved:
        raise ValueError("inspection target not approved")
    from .watchtower_inspection_client import fetch_snapshot
    snapshot = fetch_snapshot(config=ssh_config)
    address = resolve_target(snapshot, node, approved)
    config = Path(ssh_config)
    from .inspection_ssh_trust import validate_profile
    entries = [entry for entry in snapshot["nodes"]
               if isinstance(entry, dict) and entry.get("node") == node]
    if len(entries) != 1:
        raise ValueError("ambiguous host identity")
    record = entries[0]
    if record.get("host_identity_status") not in (None, "active"):
        raise ValueError("revoked host identity")
    attestation = record.get("host_identity")
    if attestation is not None:
        from .host_trust import verified_host_identity
        _, verified = verified_host_identity(snapshot, node, approved)
        validate_profile(config, node, hostname=address, require_jump=True,
                         host_key_alias=verified["host_key_alias"])
    else:
        # Legacy devices require a separately verified and pinned SSH identity.
        validate_profile(config, node, hostname=address, require_jump=True)
    # Bastion owns host keys and ProxyJump; never auto-enroll them.
    result = inspect_ssh(node, config=config, runner=runner) if runner is not None else inspect_ssh(node, config=config)
    # No resident GWay Remote agent is required on the satellite.
    # Only standard read-only systemd inspection is attempted.
    evidence = {"state": "unknown", "services": []}
    if result["ssh"] == "verified":
        services = ("ocpp-csms.service", "ocpp-reports.service")
        rows = []
        for service in services:
            try:
                proc = subprocess.run(
                    ["ssh", "-F", str(config), "-o", "BatchMode=yes",
                     "-o", "StrictHostKeyChecking=yes", node,
                     "systemctl", "show", service,
                     "--property=LoadState,ActiveState,FragmentPath", "--no-pager"],
                    capture_output=True, text=True, timeout=15, check=True,
                )
                if len(proc.stdout) > 8192:
                    raise ValueError("oversized service response")
                fields = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
                rows.append({"service": service,
                             "load_state": fields.get("LoadState", "unknown"),
                             "active_state": fields.get("ActiveState", "unknown")})
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
                rows.append({"service": service, "load_state": "unknown",
                             "active_state": "unknown"})
        from .inspection_revisions import inspect_revisions
        evidence = {"state": "reported", "services": rows, "revisions": inspect_revisions(node, config)}
    return {"node": node, "registry": "authenticated-watchtower-ssh", "remote_evidence": evidence,
            "ssh": result["ssh"], "inspection": "read-only",
            "note": "Read-only systemd and release-link evidence; missing revisions remain unknown"}
