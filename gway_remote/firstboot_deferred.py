"""Renderer for a root-owned SD claim client and persistent first-boot unit.

The client signs an HTTPS challenge with its per-card Ed25519 private key.
It never sends the private key to Watchtower or logs the bootstrap URL.
"""
from __future__ import annotations

import re

NODE = re.compile(r"gway-[0-9]{3}\Z")
USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}\Z")
IDENT = re.compile(r"[a-f0-9]{32}\Z")

CLIENT_PATH = "/usr/local/libexec/gway-sd-claim"
KEY_PATH = "/etc/gway-remote/installation.key"
SERVICE = "gway-sd-claim.service"


def firstboot_claim_source(node: str, installer: str, preparation_id: str) -> str:
    if (not NODE.fullmatch(node) or not USER.fullmatch(installer)
            or installer == "root" or not IDENT.fullmatch(preparation_id)):
        raise ValueError("invalid installation identity")
    # All substitutions are validated as restricted ASCII identifiers.
    return '''#!/usr/bin/python3
"""One-shot, signed Watchtower claim. Never log secrets."""
import base64
import json
import os
import re
import ssl
import subprocess
import tempfile
from urllib.request import build_opener, HTTPSHandler, ProxyHandler, Request, HTTPRedirectHandler
from cryptography.hazmat.primitives.serialization import load_pem_private_key

NODE = "''' + node + '''"
USER = "''' + installer + '''"
IDENT = "''' + preparation_id + '''"
BASE = "https://register.gelectriic.com"
KEY = "/etc/gway-remote/installation.key"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError("redirect denied")


def request(method, path, payload=None, maximum=4096):
    if not path.startswith("/v1/"):
        raise RuntimeError("invalid endpoint")
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()),
                          NoRedirect())
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    response = opener.open(Request(BASE + path, data=data, headers=headers, method=method),
                           timeout=25)
    try:
        if response.status != 200:
            raise RuntimeError("server rejected request")
        body = response.read(maximum + 1)
        if len(body) > maximum:
            raise RuntimeError("oversized response")
        return body
    finally:
        response.close()


def main():
    if os.geteuid() != 0 or os.uname().nodename.split(".")[0] != NODE:
        raise RuntimeError("wrong execution identity")
    with open(KEY, "rb") as file:
        private = load_pem_private_key(file.read(), password=None)
    result = json.loads(request("GET", "/v1/sd-preparations/" + IDENT + "/challenge"))
    nonce = result["challenge"]
    if not isinstance(nonce, str) or not re.fullmatch("[A-Za-z0-9_-]{43}", nonce):
        raise RuntimeError("invalid challenge")
    message = ("gway-sd-claim-v1\\n" + IDENT + "\\n" + NODE + "\\n" + nonce + "\\n").encode()
    signature = base64.urlsafe_b64encode(private.sign(message)).decode().rstrip("=")
    result = json.loads(request("POST", "/v1/sd-preparations/" + IDENT + "/claim",
                                {"challenge": nonce, "signature": signature}))
    url = result["bootstrap_url"]
    match = re.fullmatch(r"https://register\\.gelectriic\\.com(/v1/bootstrap/[A-Za-z0-9_-]{32,128})", url)
    if not match or result["device"] != NODE:
        raise RuntimeError("untrusted bootstrap response")
    # The URL is a bearer; never print it, pass it as an argument to a child
    # process, or permit redirects. It remains in memory only.
    artifact = request("GET", match.group(1), maximum=100000)
    with tempfile.TemporaryDirectory(prefix="gway-sd-", dir="/run") as directory:
        path = directory + "/bootstrap.sh"
        with open(path, "xb") as stream:
            os.chmod(path, 0o700)
            stream.write(artifact)
        subprocess.run(["/bin/sh", path, "--executor-user", USER], check=True,
                       timeout=7200, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    # Prevent repeat first-boot attempts after successful enrollment.
    os.unlink(KEY)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # No exception message: urllib errors may contain the bearer URL.
        raise SystemExit("gway-sd-claim: retryable enrollment failure")
'''


def firstboot_claim_unit() -> str:
    return """[Unit]
Description=GWay SD deferred enrollment
Wants=network-online.target
After=network-online.target cloud-final.service
ConditionPathExists=/etc/gway-remote/installation.key
StartLimitIntervalSec=0

[Service]
Type=oneshot
User=root
ExecStart=/usr/bin/python3 /usr/local/libexec/gway-sd-claim
Restart=on-failure
RestartSec=60
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
"""
