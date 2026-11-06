#!/usr/bin/env python3
"""Read-only field gate for one approved, release-pinned MCP source.

Run on the MCP backend as its actual non-root service account. Never installs,
registers, enables or restarts a source. The policy must already be provisioned.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import sys

from gway_remote.mcp_source_policy import load_source_policy
from gway_remote.mcp_source_stdio import list_source_tools


def verify_source(registration, approved_tools):
    if not registration.enabled or registration.permission != "read":
        raise ValueError("source is not enabled for read-only access")
    if pwd.getpwuid(os.geteuid()).pw_name != registration.run_as or os.geteuid() == 0:
        raise ValueError("run preflight as the approved non-root source identity")
    path = Path(registration.executable)
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("source executable missing, linked or not executable")
    # Exact immutable release location; no mutable current/checkout aliases.
    if registration.revision not in path.parts or "releases" not in path.parts:
        raise ValueError("source executable is not within its pinned release")
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError("source path contains a symlink")
    if tuple(registration.argv) != (registration.executable,):
        raise ValueError("pilot requires exact executable-only argv")
    observed = list_source_tools(registration, timeout=10)
    if observed != approved_tools:
        raise ValueError("source tool catalog differs from operator approval")
    return [tool["name"] for tool in observed]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source-id", required=True)
    args = parser.parse_args()
    try:
        registrations, approved = load_source_policy(args.policy, expected_sha256=args.sha256)
        matching = [r for r in registrations if r.source_id == args.source_id]
        if len(matching) != 1:
            raise ValueError("source not uniquely registered")
        names = verify_source(matching[0], approved[args.source_id])
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print("MCP source preflight FAILED: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"source_id": args.source_id, "revision": matching[0].revision,
                      "status": "verified", "tools": names}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
