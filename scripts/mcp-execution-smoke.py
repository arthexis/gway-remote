#!/usr/bin/env python3
"""Opt-in post-deployment gateway smoke; executes only hostname on gway-001.

Set GWAY_MCP_SMOKE_URL and an execute-scoped GWAY_MCP_SMOKE_TOKEN in the
private environment. Each invocation uses a fresh ID and never retries submit.
An uncertain response is a failure and must be investigated without replay.
"""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import time

spec = importlib.util.spec_from_file_location("mcp_smoke", Path(__file__).with_name("mcp-smoke.py"))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def smoke(url, token, transport=base.request, sleep=time.sleep):
    base.validate_url(url)
    if not token:
        raise ValueError("missing credential")
    def call(name, arguments):
        status, raw = transport(url, token, "tools/call", {"name": name, "arguments": arguments})
        if status != 200 or len(raw) > 65536:
            raise ValueError("gateway unavailable")
        result = json.loads(raw)["result"]
        if result.get("isError"):
            raise ValueError("tool rejected")
        return json.loads(result["content"][0]["text"])
    preview = call("node_exec_preview", {"node": "gway-001", "command": "hostname"})
    limit = preview["limits"]["concurrent_jobs_per_node"]
    if type(limit) is not int or not 1 <= limit <= 8:
        raise ValueError("pinned relay limits unavailable")
    rid = secrets.token_hex(16)
    print("Execution smoke request_id=" + rid, flush=True)
    accepted = call("node_exec", {"node": "gway-001", "command": "hostname", "request_id": rid})
    if accepted.get("request_id") != rid or accepted.get("status") != "dispatched":
        raise ValueError("submit not confirmed; do not retry")
    for _ in range(20):
        result = call("node_result", {"request_id": rid})
        if result.get("request_id") != rid or result.get("result_available") is False:
            raise ValueError("result unavailable")
        if result.get("status") == "succeeded":
            if result.get("exit_code") != 0 or result.get("stdout", "").strip() != "gway-001":
                raise ValueError("unexpected result")
            return rid
        if result.get("status") in ("failed", "cancelled", "unknown", "timed_out"):
            raise ValueError("job failed")
        sleep(1)
    raise ValueError("job result timed out")


def main():
    try:
        rid = smoke(os.environ.get("GWAY_MCP_SMOKE_URL", ""), os.environ.get("GWAY_MCP_SMOKE_TOKEN", ""))
    except Exception:
        print("BLOCKED: execution smoke failed; inspect the request ledger, do not retry an uncertain ID", file=sys.stderr)
        return 1
    print("PASS: pinned limits, hostname submission and result; request_id=" + rid)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
