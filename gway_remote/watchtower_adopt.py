"""Adopt an existing, operator-identified WireGuard peer into Watchtower's ledger.

No bootstrap, network changes, SSH trust pinning, or execution rights are granted.
The operator must independently verify the peer public key before invoking this.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import re
import secrets
import subprocess
from pathlib import Path

from .watchtower_enrollment import _now

_NODE = re.compile(r"gway-[0-9]{3,}$")


def _validate_key(value: str) -> str:
    try:
        if not isinstance(value, str) or len(base64.b64decode(value, validate=True)) != 32:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("invalid WireGuard public key") from None
    return value


def _peers(config: str) -> list[tuple[str, str]]:
    """Parse [Peer] blocks only; never assign identity from a comment or hostname."""
    peers = []
    section = None
    fields = {}
    def finish():
        if section == "Peer":
            if "publickey" not in fields or "allowedips" not in fields:
                raise ValueError("incomplete WireGuard peer in persistent configuration")
            peers.append((fields["publickey"], fields["allowedips"]))
    for raw in config.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            finish()
            section = line[1:-1].strip().lower().capitalize()
            fields = {}
        elif section == "Peer" and "=" in line:
            key, value = line.split("=", 1)
            key = key.strip().lower()
            if key in ("publickey", "allowedips"):
                if key in fields:
                    raise ValueError("duplicate WireGuard peer field")
                fields[key] = value.strip()
    finish()
    return peers


def adopt(ledger, *, node: str, public_key: str, config: Path,
          interface: str = "gway", dry_run: bool = False,
          runner=subprocess.run) -> dict:
    """Match operator-approved peer identity against persistent AND live WireGuard."""
    if not isinstance(node, str) or not _NODE.fullmatch(node):
        raise ValueError("invalid node")
    public_key = _validate_key(public_key)
    path = Path(config)
    if path.is_symlink() or not path.is_file():
        raise ValueError("unsafe or missing WireGuard configuration")
    matches = [(key, ips) for key, ips in _peers(path.read_text(encoding="utf-8"))
               if key == public_key]
    if len(matches) != 1:
        raise ValueError("approved peer must occur exactly once in WireGuard configuration")
    try:
        persistent = [ipaddress.ip_interface(ip.strip()) for ip in matches[0][1].split(",")]
    except ValueError as exc:
        raise ValueError("invalid peer AllowedIPs") from exc
    if len(persistent) != 1 or persistent[0].version != 4 or persistent[0].network.prefixlen != 32:
        raise ValueError("adoption requires exactly one IPv4 /32 peer address")
    address = persistent[0]
    if address.ip not in ledger.network or address.ip == ledger.gateway:
        raise ValueError("peer address outside approved Watchtower pool")
    try:
        result = runner(["wg", "show", interface, "allowed-ips"],
                        check=True, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("live WireGuard peer inspection failed") from exc
    runtime = []
    for line in result.stdout.splitlines():
        columns = line.split(None, 1)
        if len(columns) != 2:
            raise RuntimeError("malformed live WireGuard peer inventory")
        runtime.append((columns[0], columns[1].strip()))
    live = [ips for key, ips in runtime if key == public_key]
    if live != [str(address)]:
        raise ValueError("live WireGuard peer does not match persistent /32 identity")
    if any(key != public_key and str(address) in [part.strip() for part in ips.split(",")] for key, ips in runtime):
        raise ValueError("peer address conflicts with another live WireGuard peer")

    # A single IMMEDIATE transaction excludes concurrent enrollment and conflicting IDs.
    with (ledger._connect() if dry_run else ledger._transaction()) as db:
        existing = db.execute("SELECT * FROM devices WHERE device=?", (node,)).fetchone()
        conflict = db.execute("SELECT device FROM devices WHERE (public_key=? OR address=?) AND device!=?",
                              (public_key, str(address), node)).fetchone()
        if conflict is not None:
            raise ValueError("peer identity or address already registered to another node")
        if existing is not None:
            if (existing["state"] != "active" or existing["public_key"] != public_key
                    or existing["address"] != str(address)):
                raise ValueError("existing node identity conflicts; adoption refused")
            state = "already_adopted"
        else:
            state = "would_adopt" if dry_run else "adopted"
            if not dry_run:
                operation_id = secrets.token_hex(16)
                now = _now()
                # No invitation or authentication token is created by adoption.
                db.execute(
                    "INSERT INTO operations(id,device,public_key,address,token_hash,state,detail,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,'committed','adopt',?,?)",
                    (operation_id, node, public_key, str(address), hashlib.sha256(("adopt:" + operation_id).encode("ascii")).hexdigest(), now, now))
                db.execute(
                    "INSERT INTO devices(device,public_key,address,state,operation_id) "
                    "VALUES(?,?,?,'active',?)",
                    (node, public_key, str(address), operation_id))
    return {"node": node, "address": str(address), "state": state,
            "identity_verified": False, "reachable": "unknown",
            "execute_available": False, "wireguard_changed": False}
