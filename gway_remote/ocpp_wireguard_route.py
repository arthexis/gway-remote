"""Read-only IPv4 route selection for the OCPP-over-WireGuard lab (#628).

Route selection is *not* proof that WireGuard peers, hub forwarding, firewall,
TCP/9000, WebSocket or OCPP identity/authentication actually work.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
from typing import Any

SCHEMA = "gway-remote/ocpp-wg-route-preflight/v1"
WG_INTERFACE = "gway"
LAN_INTERFACES = frozenset({"eth0", "wlan0", "wlan1"})
MAX_ROUTE_BYTES = 65536


def _destination(value: str) -> str:
    """Accept only a literal unicast IPv4 destination (no host/DNS/port/CIDR)."""
    address = ipaddress.IPv4Address(value)
    if (address.is_multicast or address.is_unspecified or address.is_loopback
            or address.is_link_local or str(address) == "255.255.255.255"):
        raise ValueError("invalid unicast IPv4 destination")
    return str(address)


def classify_route(route_json: str, destination: str) -> dict[str, Any]:
    """Classify one `ip -4 -j route get ADDRESS` record, never issue network I/O.

    via_hub only means the local kernel selected the *existing* gway device.
    It does NOT establish which peer, if any, accepts the destination.
    via_lan means a directly attached LAN device without a next-hop gateway.
    """
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "selection": "unknown",
        "interface": None,
        "via_gateway": None,
        "reason": "route_unavailable",
    }
    try:
        target = _destination(destination)
    except (ipaddress.AddressValueError, ValueError):
        result["reason"] = "invalid_destination"
        return result

    if not isinstance(route_json, str) or len(route_json) > MAX_ROUTE_BYTES:
        result["reason"] = "invalid_route_json"
        return result
    try:
        entries = json.loads(route_json)
    except (TypeError, ValueError):
        result["reason"] = "invalid_route_json"
        return result
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        result["reason"] = "ambiguous_route"
        return result

    route = entries[0]
    if route.get("dst") != target:
        result["reason"] = "destination_mismatch"
        return result
    interface = route.get("dev")
    if not isinstance(interface, str) or not interface:
        result["reason"] = "missing_interface"
        return result

    gateway = route.get("gateway")
    if gateway is not None:
        try:
            ipaddress.IPv4Address(gateway)
        except (ipaddress.AddressValueError, ValueError, TypeError):
            result["reason"] = "invalid_gateway"
            return result

    result["interface"] = interface
    result["via_gateway"] = gateway is not None
    result["reason"] = "route_selected"
    if route.get("type") in ("unreachable", "blackhole", "prohibit"):
        result["selection"] = "unexpected"
    elif interface == WG_INTERFACE and gateway is None:
        result["selection"] = "via_hub"
    elif interface in LAN_INTERFACES and gateway is None:
        result["selection"] = "via_lan"
    else:
        result["selection"] = "unexpected"
    return result


def inspect_route(destination: str, *, run=subprocess.run) -> dict[str, Any]:
    """Execute only the read-only kernel route lookup, with bounded output."""
    try:
        address = _destination(destination)
    except (ipaddress.AddressValueError, ValueError):
        return classify_route("", destination)
    try:
        completed = run(
            ["ip", "-4", "-j", "route", "get", address],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return classify_route("", address)
    if completed.returncode != 0:
        return classify_route("", address)
    return classify_route(completed.stdout, address)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only local route preflight; does not probe or connect to the destination."
    )
    parser.add_argument("destination", help="approved target's literal VPN or LAN IPv4")
    args = parser.parse_args(argv)
    report = inspect_route(args.destination)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["selection"] in ("via_hub", "via_lan") else 2


if __name__ == "__main__":
    raise SystemExit(main())
