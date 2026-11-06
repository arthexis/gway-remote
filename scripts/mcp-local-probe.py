#!/usr/bin/env python3
"""Minimal local MCP HTTP diagnostic; no token or response bodies are printed."""
import argparse
import json
from pathlib import Path
import urllib.request


def read_token(path):
    # The user-owned service EnvironmentFile is the only credential source.
    st = path.stat()
    if st.st_mode & 0o077:
        raise ValueError("credential file permissions are too broad")
    for line in path.read_text().splitlines():
        if line.startswith("GWAY_MCP_BEARER_TOKEN="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if value and not any(c.isspace() for c in value):
                return value
    raise ValueError("local MCP bearer credential unavailable")


def probe(method, params, *, credential_path, url="http://127.0.0.1:8770/mcp"):
    if url != "http://127.0.0.1:8770/mcp":
        raise ValueError("only the fixed loopback MCP endpoint is supported")
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(url, data=payload, method="POST", headers={
        "Authorization": "Bearer " + read_token(credential_path),
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })
    with urllib.request.urlopen(request, timeout=12) as response:
        data = json.load(response)
    if not isinstance(data, dict) or data.get("id") != 1 or "error" in data:
        raise ValueError("MCP returned an invalid or failed response")
    return data["result"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--list", action="store_true", help="show tool names only")
    actions.add_argument("--call", choices=("odoo__customer_search", "odoo__product_search",
                                            "odoo__quotation_search"),
                         help="perform one bounded read-only Odoo smoke query")
    parser.add_argument("--query", help="search term; required with --call")
    parser.add_argument("--credential-file", type=Path,
                        default=Path.home() / ".config/gway-remote/mcp.env",
                        help="local user-owned MCP EnvironmentFile")
    args = parser.parse_args(argv)
    if args.call and (not args.query or len(args.query) > 120):
        parser.error("--call requires --query of 1–120 characters")
    if args.list and args.query:
        parser.error("--query requires --call")
    try:
        if args.list:
            result = probe("tools/list", {}, credential_path=args.credential_file)
            names = [tool["name"] for tool in result["tools"]]
            print(json.dumps({"status": "ok", "count": len(names), "tools": names}))
        else:
            result = probe("tools/call", {"name": args.call,
                "arguments": {"query": args.query, "limit": 1}},
                credential_path=args.credential_file)
            print(json.dumps({"status": "ok", "tool": args.call,
                              "isError": result.get("isError", False)}))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        # Never echo exception text: URLs, headers, or server responses may be sensitive.
        print(json.dumps({"status": "failed", "reason": type(exc).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
