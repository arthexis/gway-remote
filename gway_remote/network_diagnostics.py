"""Read-only, stable local network observations for the appliance interfaces."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import ipaddress
import json
import subprocess

INTERFACES = ("eth0", "wlan0", "wlan1")
SYS_NET = Path("/sys/class/net")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii").strip() or None
    except (OSError, ValueError, UnicodeError):
        return None


def _ipv4_addresses(*, command: tuple[str, ...] = ("ip", "-4", "-j", "address", "show")) -> dict:
    """Read only local interface addresses; never modify routing or links."""
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
        if process.returncode != 0 or len(process.stdout) > 262144:
            return {}
        entries = json.loads(process.stdout)
        if not isinstance(entries, list):
            return {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}
    addresses = {}
    for item in entries:
        if not isinstance(item, dict) or item.get("ifname") not in INTERFACES:
            continue
        values = []
        for address in item.get("addr_info", []):
            if not isinstance(address, dict) or address.get("family") != "inet":
                continue
            value = address.get("local")
            try:
                parsed = ipaddress.IPv4Address(value)
            except (ValueError, ipaddress.AddressValueError):
                continue
            if str(parsed) not in values:
                values.append(str(parsed))
        addresses[item["ifname"]] = values
    return addresses


def inspect(*, sys_net: Path = SYS_NET, addresses: dict | None = None) -> dict:
    """A missing interface is different from a down interface or no IPv4."""
    if addresses is None:
        addresses = _ipv4_addresses()
    interfaces = {}
    for name in INTERFACES:
        path = sys_net / name
        present = path.exists()
        state = _read(path / "operstate") if present else None
        flags = _read(path / "flags") if present else None
        try:
            up = bool(int(flags, 0) & 1) if flags is not None else False
        except ValueError:
            up = False
        mac = _read(path / "address") if present else None
        interfaces[name] = {
            "present": present,
            "up": up,
            "operstate": state,
            "ipv4": addresses.get(name, []) if present else [],
            "mac": mac,
        }
    return {
        "schema": "gway-remote/network/v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "interfaces": interfaces,
    }


def format_network(report: dict) -> str:
    lines = ["Local network interfaces (read-only)"]
    for name, item in report["interfaces"].items():
        if not item["present"]:
            lines.append(f"{name}: absent")
            continue
        addresses = ", ".join(item["ipv4"]) or "no IPv4"
        lines.append(f"{name}: {'up' if item['up'] else 'down'} "
                     f"({item['operstate'] or 'unknown'}), {addresses}")
    return "\n".join(lines)
