"""Bounded, read-only discovery of a CSMS on the wired test interface.

No network scan, shell interpolation, or OCPP messages are performed.
"""
import ipaddress
import json
import socket
import subprocess

INTERFACE = "eth0"
DEFAULT_PORT = 9000


def _ip(*args):
    try:
        result = subprocess.run(["ip", "-j", *args], capture_output=True, text=True,
                                timeout=3, check=True)
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []


def _networks():
    networks = []
    addresses = []
    for item in _ip("address", "show", "dev", INTERFACE):
        for address in item.get("addr_info", []):
            if address.get("family") != "inet":
                continue
            try:
                ip = ipaddress.IPv4Address(address["local"])
                network = ipaddress.IPv4Network(
                    f'{ip}/{int(address["prefixlen"])}', strict=False)
                addresses.append(str(ip))
                networks.append(network)
            except (ValueError, KeyError, TypeError):
                continue
    return addresses, networks


def _on_link(host, networks):
    try:
        address = ipaddress.IPv4Address(host)
        return not (address.is_loopback or address.is_multicast or address.is_unspecified) and any(
            address in network for network in networks)
    except ipaddress.AddressValueError:
        return False


def _reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.7):
            return True
    except (OSError, TimeoutError):
        return False


def discover(*, host=None, port=DEFAULT_PORT):
    """Return local wired addresses and reachable peer candidates.

    A reachable TCP port is *not* proof of a functioning OCPP CSMS.
    Explicit hosts must be numeric IPv4 addresses on the wired subnet.
    """
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid_port")
    addresses, networks = _networks()
    if host is not None and (not isinstance(host, str) or not _on_link(host, networks)):
        raise ValueError("target_must_be_on_wired_subnet")
    candidates = []
    if host is not None:
        candidates = [host]
    else:
        for neighbor in _ip("neighbor", "show", "dev", INTERFACE):
            candidate = neighbor.get("dst", "")
            if _on_link(candidate, networks) and neighbor.get("state") not in (
                "FAILED", "INCOMPLETE"):
                candidates.append(candidate)
    peers = []
    for candidate in list(dict.fromkeys(candidates))[:16]:
        reachable = _reachable(candidate, port)
        peers.append({"host": candidate, "port": port, "tcp_reachable": reachable,
                      "url_example": f"ws://{candidate}:{port}/SIM001"})
    return {"interface": INTERFACE, "addresses": addresses, "port": port,
            "peers": peers, "note": "TCP reachability only; OCPP handshake not verified"}
