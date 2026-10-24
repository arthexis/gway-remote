#!/usr/bin/env python3
"""Read-only MCP smoke test. No credentials in argv, URLs or output.

Usage:
  GWAY_MCP_SMOKE_URL=https://remote.arthexis.com/mcp \
  GWAY_MCP_SMOKE_TOKEN=... python3 scripts/mcp-smoke.py
Only use a token provisioned for this endpoint. Never use the mobile API token.
"""
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

EXPECTED = {"agent_list_issues", "agent_status", "agent_preview", "agent_observe"}
ACCEPT = "application/json, text/event-stream"
PROTOCOL = "2025-03-26"


def request(url, token, method, payload=None):
    headers = {"Accept": ACCEPT, "MCP-Protocol-Version": PROTOCOL}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        headers["Content-Type"] = "application/json"
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       **({"params": payload} if payload is not None else {})}).encode()
    req = Request(url, body, headers, method="POST")
    try:
        with urlopen(req, timeout=8) as response:
            return response.status, response.read(65537)
    except HTTPError as exc:
        exc.close()
        return exc.code, b""


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("expected HTTPS URL without embedded credentials")
    if parts.query or parts.fragment or parts.path != "/mcp":
        raise ValueError("expected dedicated /mcp endpoint without query or fragment")


def smoke(url, token, transport=request):
    validate_url(url)
    if not token:
        raise ValueError("missing smoke-test token (environment only)")
    denied, _ = transport(url, None, "tools/list")
    if denied not in (401, 403):
        raise ValueError("unauthenticated requests must be rejected (401 or 403)")
    status, raw = transport(url, token, "initialize", {"protocolVersion": PROTOCOL,
        "capabilities": {}, "clientInfo": {"name": "gway-smoke", "version": "1"}})
    if status != 200 or len(raw) > 65536:
        raise ValueError("MCP initialization failed")
    initialized = json.loads(raw)
    if initialized.get("result", {}).get("protocolVersion") != PROTOCOL:
        raise ValueError("unexpected MCP protocol version")
    status, raw = transport(url, token, "tools/list", {})
    if status != 200 or len(raw) > 65536:
        raise ValueError("MCP tools/list failed")
    data = json.loads(raw)
    tools = data.get("result", {}).get("tools", [])
    names = {t.get("name") for t in tools}
    if names != EXPECTED or not all(t.get("annotations", {}).get("readOnlyHint") is True
                                     for t in tools):
        raise ValueError("unexpected or mutating MCP tool inventory")
    return sorted(names)


def main():
    try:
        names = smoke(os.environ.get("GWAY_MCP_SMOKE_URL", ""),
                      os.environ.get("GWAY_MCP_SMOKE_TOKEN", ""))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, URLError, TimeoutError) as exc:
        # Do not output untrusted remote response or exception: may contain secret URL.
        print("BLOCKED: MCP smoke validation failed; check private logs securely", file=sys.stderr)
        return 1
    print("PASS: unauthenticated rejected; initialize OK; read-only tools: " + ", ".join(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
