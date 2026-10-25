"""Standalone satellite WireGuard bootstrap. No GWAY classic dependency."""
from __future__ import annotations

import argparse
import base64
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

DEFAULT_URL = "https://register.gelectriic.com/v1/enroll"
KEY_RE = re.compile(r"^[A-Za-z0-9+/]{43}=$")
DEVICE_RE = re.compile(r"^gway-[0-9]{3,}$")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("enrollment redirects are forbidden")


def _key(value):
    if not isinstance(value, str) or not KEY_RE.fullmatch(value):
        raise ValueError("invalid WireGuard public key")
    if len(base64.b64decode(value, validate=True)) != 32:
        raise ValueError("invalid WireGuard public key")
    return value


def _run(*args, input=None):
    return subprocess.run(args, input=input, capture_output=True, text=True, check=True).stdout.strip()


def _identity(path):
    if path.is_symlink():
        raise ValueError("refusing symlink configuration")
    if path.exists():
        if path.stat().st_mode & 0o077:
            raise PermissionError("existing WireGuard configuration is not private")
        content = path.read_text()
        match = re.search(r"(?m)^PrivateKey\s*=\s*(\S+)\s*$", content)
        if not match:
            raise ValueError("existing configuration lacks private key")
        private = match.group(1)
        return private, _key(_run("wg", "pubkey", input=private + "\n")), content
    pending = path.with_name(path.name + ".pending-key")
    if pending.is_symlink():
        raise ValueError("unsafe pending key")
    if pending.exists():
        if pending.stat().st_mode & 0o077:
            raise PermissionError("pending key is not private")
        private = pending.read_text().strip()
    else:
        private = _run("wg", "genkey")
        _atomic_new(pending, private + "\n")
    return private, _key(_run("wg", "pubkey", input=private + "\n")), None


def _enroll(url, device, public, token):
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "register.gelectriic.com"
            or parsed.port not in (None, 443) or parsed.path != "/v1/enroll"
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValueError("enrollment must use the approved HTTPS endpoint")
    payload = json.dumps({"device": device, "public_key": public, "token": token}).encode()
    request = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            if response.status != 200:
                raise RuntimeError("enrollment rejected")
            data = response.read(4097)
    except (HTTPError, URLError) as exc:
        raise RuntimeError("enrollment unavailable or rejected") from exc
    if len(data) > 4096:
        raise ValueError("oversized enrollment response")
    return json.loads(data)


def _validate(response, device, public, server_key):
    if not isinstance(response, dict) or response.get("device") != device or response.get("public_key") != public:
        raise ValueError("enrollment identity mismatch")
    _key(server_key)
    if response.get("server_public_key") != server_key:
        raise ValueError("Watchtower public key mismatch")
    address = ipaddress.ip_interface(response["address"])
    if address.version != 4 or address.network.prefixlen != 32 or not address.ip.is_private:
        raise ValueError("invalid assigned address")
    endpoint = response.get("server_endpoint")
    if endpoint != "register.gelectriic.com:51820":
        raise ValueError("unexpected WireGuard endpoint")
    gateway = ipaddress.ip_address(response["server_tunnel_ip"])
    if gateway.version != 4 or not gateway.is_private or gateway == address.ip:
        raise ValueError("invalid Watchtower tunnel address")
    return str(address), endpoint, str(gateway)


def _atomic_new(path, content):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".gway-")
    try:
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() or path.is_symlink():
            raise FileExistsError("existing WireGuard configuration must not be replaced")
        os.link(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def bootstrap(device, server_key, token, *, config=Path("/etc/wireguard/gway.conf"), url=DEFAULT_URL):
    if os.geteuid() != 0:
        raise PermissionError("bootstrap requires root")
    if not DEVICE_RE.fullmatch(device):
        raise ValueError("invalid device name")
    server_key = _key(server_key)
    private, public, existing = _identity(config)
    if existing is not None:
        if f"PublicKey = {server_key}" not in existing:
            raise ValueError("existing tunnel differs; refusing replacement")
        _run("systemctl", "enable", "--now", "wg-quick@gway.service")
        return {"device": device, "configured": True, "reused": True}
    response = _enroll(url, device, public, token)
    address, endpoint, gateway = _validate(response, device, public, server_key)
    config_text = (f"[Interface]\nAddress = {address}\nPrivateKey = {private}\n\n"
                   f"[Peer]\nPublicKey = {server_key}\nEndpoint = {endpoint}\n"
                   f"AllowedIPs = {gateway}/32\nPersistentKeepalive = 25\n")
    _atomic_new(config, config_text)
    config.with_name(config.name + ".pending-key").unlink(missing_ok=True)
    _run("systemctl", "enable", "--now", "wg-quick@gway.service")
    return {"device": device, "configured": True, "reused": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Standalone GWAY Remote WireGuard satellite client")
    sub = parser.add_subparsers(dest="action", required=True)
    boot = sub.add_parser("bootstrap")
    boot.add_argument("--device", required=True)
    boot.add_argument("--server-public-key", required=True, help="Watchtower WireGuard public key, verified out of band")
    boot.add_argument("--token-file", type=Path)
    boot.add_argument("--url", default=DEFAULT_URL)
    status = sub.add_parser("status")
    status.add_argument("--config", type=Path, default=Path("/etc/wireguard/gway.conf"))
    args = parser.parse_args(argv)
    try:
        if args.action == "status":
            print(json.dumps({"configured": args.config.is_file(), "interface": "gway"}))
        else:
            if args.token_file:
                if args.token_file.stat().st_mode & 0o077:
                    raise PermissionError("invitation file must be private")
                token = args.token_file.read_text().strip()
            else:
                token = getpass.getpass("Watchtower invitation token: ")
            if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
                raise ValueError("invalid invitation")
            print(json.dumps(bootstrap(args.device, args.server_public_key, token, url=args.url)))
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, "wire bootstrap failed: " + type(exc).__name__ + "\n")


if __name__ == "__main__":
    main()
