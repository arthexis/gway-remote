"""Read-only controller inspection primitives; no network-policy or SSH trust mutation."""
from __future__ import annotations

import ipaddress
import json
import re
import subprocess
from pathlib import Path

_NODE = re.compile(r"gway-[0-9]{3,}$")


def registry_snapshot(ledger):
    """Produce sanitized active identities from Watchtower's authoritative ledger.

    This must be transferred to the controller over an independently authenticated
    administrative channel, never served from the public enrollment endpoint.
    """
    with ledger._connect() as db:
        rows = db.execute(
            "SELECT device, address, state FROM devices ORDER BY device"
        ).fetchall()
    return {"schema": 1, "nodes": [
        {"node": row["device"], "address": row["address"], "state": row["state"]}
        for row in rows
    ]}


def resolve_target(snapshot, node, approved):
    """Bind a selected approved node to exactly one active registry identity."""
    if not isinstance(node, str) or not _NODE.fullmatch(node) or node not in approved:
        raise ValueError("inspection target not approved")
    if not isinstance(snapshot, dict) or snapshot.get("schema") != 1:
        raise ValueError("invalid trusted registry snapshot")
    nodes = snapshot.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("invalid trusted registry snapshot")
    matches = [x for x in nodes if isinstance(x, dict) and x.get("node") == node]
    if len(matches) != 1 or matches[0].get("state") != "active":
        raise ValueError("target is missing, ambiguous or inactive")
    address = matches[0].get("address")
    try:
        ip = ipaddress.ip_interface(address)
        if ip.version != 4 or ip.network.prefixlen != 32 or not ip.ip.is_private:
            raise ValueError("invalid management address")
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid management address") from exc
    return str(ip.ip)


def inspect_ssh(node, *, runner=subprocess.run):
    """Probe a preconfigured Bastion/ProxyJump alias, never establish SSH trust.

    SSH configuration and known_hosts are preconditions owned by Bastion/#264.
    A fixed command and no shell prevent arbitrary remote execution.
    """
    if not isinstance(node, str) or not _NODE.fullmatch(node):
        raise ValueError("invalid node")
    command = [
        "ssh", "-F", "/etc/gway-remote/inspection-ssh.conf",
        "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=8", "-o", "ConnectionAttempts=1",
        node, "true",
    ]
    try:
        result = runner(command, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {"node": node, "ssh": "unavailable"}
    return {"node": node, "ssh": "verified" if result.returncode == 0 else "blocked"}
