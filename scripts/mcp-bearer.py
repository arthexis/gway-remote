#!/usr/bin/env python3
"""Run on Watchtower console only. Never paste issued credentials into chat."""
import argparse
import os
import sys
from gway_remote.mcp_bearer import BearerRegistry

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--database", default="/var/lib/gway-remote/mcp-credentials.sqlite3")
    cmd = p.add_subparsers(dest="command", required=True)
    issue = cmd.add_parser("issue")
    issue.add_argument("--days", type=int, default=30)
    revoke = cmd.add_parser("revoke")
    revoke.add_argument("key_id")
    args = p.parse_args()
    if os.geteuid() == 0:
        print("Run as the dedicated service owner, not root.", file=sys.stderr)
        return 2
    registry = BearerRegistry(args.database)
    if args.command == "issue":
        if not 1 <= args.days <= 90:
            p.error("--days must be 1..90")
        print(registry.issue(lifetime=args.days * 86400))
        print("SAVE THIS IN A PROTECTED SECRET STORE. IT CANNOT BE RETRIEVED AGAIN.", file=sys.stderr)
    else:
        if not registry.revoke(args.key_id):
            print("Credential not found or already revoked", file=sys.stderr)
            return 1
        print("Revoked")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
