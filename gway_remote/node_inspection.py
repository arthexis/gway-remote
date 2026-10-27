"""Read-only controller inspection primitives; no network-policy or SSH trust mutation."""
from __future__ import annotations

import ipaddress
import json
import re
import subprocess
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_NODE = re.compile(r"gway-[0-9]{3,}$")


def registry_snapshot(ledger):
    """Produce sanitized active identities from Watchtower's authoritative ledger.

    This must be transferred to the controller over an independently authenticated
    administrative channel, never served from the public enrollment endpoint.
    """
    return snapshot_from_path(ledger.path)


def snapshot_from_path(path):
    """Never construct Ledger: its initializer performs schema and chmod writes."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Watchtower ledger unavailable")
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as db:
        db.execute("PRAGMA query_only=ON")
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT device, address, state FROM devices ORDER BY device"
        ).fetchall()
    nodes = [{"node": row["device"], "address": row["address"], "state": row["state"]}
             for row in rows]
    # Older Watchtower ledgers have no host attestation records. They remain
    # inspectable only through independently pinned SSH trust.
    with sqlite3.connect(uri, uri=True, timeout=5) as db:
        db.execute("PRAGMA query_only=ON")
        present = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='host_identities'"
        ).fetchone()
        if present:
            identities = db.execute(
                "SELECT device, wireguard_identity, host_public_key, enrollment_binding, "
                "state, created_at, valid_until FROM host_identities WHERE state='active'"
            ).fetchall()
            by_device = {item["node"]: item for item in nodes if item["state"] == "active"}
            for device, wg, host, binding, state, created, expiry in identities:
                node = by_device.get(device)
                if node is not None:
                    node["host_identity"] = {
                        "schema": 1, "node": device, "wireguard_identity": wg,
                        "host_public_key": host, "enrollment_binding": binding,
                        "state": state, "rotation_state": "stable",
                        "created_at": created, "valid_until": expiry,
                    }
    return {"schema": 2, "generated_at": datetime.now(timezone.utc).isoformat(),
            "nodes": nodes}


def resolve_target(snapshot, node, approved):
    """Bind a selected approved node to exactly one active registry identity."""
    if not isinstance(node, str) or not _NODE.fullmatch(node) or node not in approved:
        raise ValueError("inspection target not approved")
    if not isinstance(snapshot, dict) or snapshot.get("schema") != 2:
        raise ValueError("invalid trusted registry snapshot")
    try:
        generated = datetime.fromisoformat(snapshot["generated_at"])
        if generated.tzinfo is None:
            raise ValueError("naive registry timestamp")
        age = (datetime.now(timezone.utc) - generated).total_seconds()
        if age < -60 or age > 300:
            raise ValueError("stale registry snapshot")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("stale or invalid registry timestamp") from exc
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


def inspect_ssh(node, *, config="/etc/gway-remote/inspection-ssh.conf", runner=subprocess.run):
    """Probe a preconfigured Bastion/ProxyJump alias, never establish SSH trust.

    SSH configuration and known_hosts are preconditions owned by Bastion/#264.
    A fixed command and no shell prevent arbitrary remote execution.
    """
    if not isinstance(node, str) or not _NODE.fullmatch(node):
        raise ValueError("invalid node")
    command = [
        "ssh", "-F", str(config),
        "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=8", "-o", "ConnectionAttempts=1",
        node, "true",
    ]
    try:
        result = runner(command, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {"node": node, "ssh": "unavailable"}
    return {"node": node, "ssh": "verified" if result.returncode == 0 else "blocked"}
