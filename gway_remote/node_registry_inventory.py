"""Derived read-only node inventory for MCP and Ansible from Watchtower enrollment.

Enrollment SQLite is the sole authority for registered identity. A root-owned,
short-lived snapshot crosses the privilege boundary to the read-only MCP
gateway; neither MCP nor Ansible can add or approve a node here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import grp
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

from .node_inspection import snapshot_from_path

LEDGER = Path("/var/lib/gway-remote/watchtower/ledger.sqlite3")
SNAPSHOT = Path("/var/lib/gway-mcp-auth/node-inventory.json")
READER_GROUP = "gway-mcp-read"
MAX_BYTES = 131072
MAX_AGE_SECONDS = 120
NODE = re.compile(r"gway-[0-9]{3,}$")


def _stamp():
    return datetime.now(timezone.utc).isoformat()


def _age(value):
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            raise ValueError("naive timestamp")
        seconds = (datetime.now(timezone.utc) - dt).total_seconds()
        if not -60 <= seconds <= MAX_AGE_SECONDS:
            raise ValueError("stale node inventory")
    except (TypeError, ValueError) as exc:
        raise ValueError("stale or invalid node inventory") from exc


def _identity(row):
    if type(row) is not dict or row.get("state") != "active":
        return False
    host = row.get("host_identity")
    if type(host) is not dict or host.get("state") != "active":
        return False
    if host.get("node") != row.get("node") or host.get("wireguard_identity") != row.get("wireguard_identity"):
        return False
    try:
        expiry = datetime.fromisoformat(host["valid_until"])
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            return False
    except (KeyError, ValueError, TypeError):
        return False
    return bool(host.get("host_public_key"))


def _grants(ledger):
    """Read eligibility from the SAME authoritative enrollment database, never a second registry."""
    path = Path(ledger)
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_eligibility'").fetchone():
            return {}
        return {node: (key, enabled == 1) for node, key, enabled in db.execute(
            "SELECT device,host_public_key,enabled FROM execution_eligibility")}


def build(ledger=LEDGER, *, probe=False):
    """Rebuild from read-only enrollment tables; never infer reachability."""
    registry = snapshot_from_path(ledger)
    from .node_reachability import observe
    observations = observe(ledger) if probe else {}
    grants = _grants(ledger)
    result = []
    for row in registry["nodes"]:
        name = row.get("node")
        if not isinstance(name, str) or not NODE.fullmatch(name):
            continue
        if row.get("state") != "active":
            continue
        try:
            address = ipaddress.ip_interface(row["address"])
            if address.version != 4 or address.network.prefixlen != 32 or not address.ip.is_private:
                continue
        except (ValueError, TypeError, KeyError):
            continue
        identity = row.get("host_identity") or {}
        bound_key, granted = grants.get(name, ("", False))
        eligible = bool(granted and _identity(row)
                        and identity.get("host_public_key") == bound_key)
        result.append({
            "node": name,
            "registered": True,
            "registration_state": "active",
            "identity_verified": _identity(row),
            "address": str(address.ip),  # private management address, not an execution target
            "reachable": observations.get(name, {}).get("reachable", "unknown"),
            "observed_at": observations.get(name, {}).get("observed_at"),
            "capabilities": ["inventory"],
            "execute_eligible": eligible,
            "execute_available": False,
        })
    return {"schema": 1, "source": "watchtower-enrollment-ledger",
            "generated_at": _stamp(), "nodes": sorted(result, key=lambda x: x["node"])}


def publish(data, path=SNAPSHOT):
    """Publish a root-owned immutable snapshot for the unprivileged gateway."""
    if os.geteuid() != 0:
        raise ValueError("inventory publication requires root")
    if path != SNAPSHOT:
        raise ValueError("only the canonical inventory destination is supported")
    parent = path.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o007 or info.st_mode & 0o020:
        raise ValueError("unsafe node inventory directory")
    if path.is_symlink():
        raise ValueError("unsafe node inventory link")
    group = grp.getgrnam(READER_GROUP).gr_gid
    encoded = (json.dumps(data, separators=(",", ":"), sort_keys=True) + "\n").encode()
    if len(encoded) > MAX_BYTES:
        raise ValueError("inventory exceeds size limit")
    fd, name = tempfile.mkstemp(prefix=".node-inventory-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchown(stream.fileno(), 0, group)
            os.fchmod(stream.fileno(), 0o640)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load(path=SNAPSHOT, *, require_owner=True):
    """Read the short-lived view; fail closed if stale or untrusted."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES or info.st_size < 2:
        raise ValueError("unsafe node inventory")
    if require_owner and (info.st_uid != 0 or info.st_mode & 0o027):
        raise ValueError("untrusted node inventory permissions")
    with path.open("rb") as stream:
        data = json.loads(stream.read(MAX_BYTES + 1))
    if type(data) is not dict or data.get("schema") != 1 or data.get("source") != "watchtower-enrollment-ledger":
        raise ValueError("invalid node inventory schema")
    _age(data.get("generated_at"))
    nodes = data.get("nodes")
    if type(nodes) is not list or len(nodes) > 1000:
        raise ValueError("invalid node inventory list")
    seen = set()
    for row in nodes:
        if (type(row) is not dict or type(row.get("node")) is not str
                or not NODE.fullmatch(row["node"]) or row["node"] in seen
                or row.get("registration_state") != "active"
                or row.get("registered") is not True
                or type(row.get("identity_verified")) is not bool
                or row.get("reachable") not in ("unknown", "reachable")
                or (row.get("reachable") == "unknown" and row.get("observed_at") is not None)
                or (row.get("reachable") == "reachable" and not isinstance(row.get("observed_at"), str))
                or type(row.get("execute_eligible")) is not bool
                or row.get("execute_available") is not False):
            raise ValueError("invalid inventory node")
        seen.add(row["node"])
    return data


def public_nodes(path=SNAPSHOT, *, execution_enabled=False):
    """Remove management addresses and identifying host keys from MCP output."""
    data = load(path)
    return {
        "schema": data["schema"], "source": data["source"],
        "generated_at": data["generated_at"],
        "nodes": [
            {"node": row["node"], "registered": True,
             "identity_verified": row["identity_verified"],
             "reachable": row["reachable"], "observed_at": row["observed_at"],
             "capabilities": ["inventory"],
             "execute_available": bool(execution_enabled and row["execute_eligible"]
                                       and row["identity_verified"] and row["reachable"] == "reachable")}
            for row in data["nodes"]
        ],
    }


def ansible_inventory(path=SNAPSHOT):
    """Dynamic inventory: identity only; never grants management permissions."""
    data = load(path)
    return {"_meta": {"hostvars": {
        row["node"]: {
            "gway_registered": True,
            "gway_identity_verified": row["identity_verified"],
            "gway_management_address": row["address"],
            "gway_reachability": row["reachable"],
            "gway_execute_available": False,
        } for row in data["nodes"]
    }}, "all": {"children": ["gway_enrolled"]},
            "gway_enrolled": {"hosts": [row["node"] for row in data["nodes"]]}}


def capabilities(node, path=SNAPSHOT, *, execution_enabled=False):
    if not isinstance(node, str) or not NODE.fullmatch(node):
        raise ValueError("invalid node")
    rows = public_nodes(path, execution_enabled=execution_enabled)["nodes"]
    found = next((row for row in rows if row["node"] == node), None)
    if found is None:
        raise ValueError("unregistered node")
    return {"node": node, "capabilities": ["inventory"],
            "execute_available": found["execute_available"], "limits": None,
            "approval_required": False, "reachable": found["reachable"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Derived enrollment inventory")
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--publish", action="store_true")
    options.add_argument("--ansible", action="store_true")
    options.add_argument("--list", action="store_true")
    parser.add_argument("--host", default=None)
    args = parser.parse_args(argv)
    if args.publish:
        if args.host:
            parser.error("--host requires --ansible")
        publish(build(probe=True))
        return 0
    if args.ansible:
        data = ansible_inventory()
        if args.host:
            data = data["_meta"]["hostvars"].get(args.host, {})
    else:
        if args.host:
            parser.error("--host requires --ansible")
        data = public_nodes()
    print(json.dumps(data, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
