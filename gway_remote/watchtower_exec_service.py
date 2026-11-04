"""Root-pinned opt-in Watchtower execution and local credential issuance."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import stat

from . import node_registry_inventory
from .watchtower_exec_transport import RequestLedger, PinnedNode, SSHTransport, DormantRelay
from .watchtower_exec_auth import AuthorizedExecution

CONFIG = Path("/etc/gway-mcp/execute.json")


def load_service(path=CONFIG):
    info = Path(path).lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o022 or info.st_size > 4096):
        raise PermissionError("untrusted execution configuration")
    config = json.loads(Path(path).read_text())
    required = {"enabled","node","address","ssh_host_alias","known_hosts",
                "identity_file","host_key_sha256","remote_user"}
    if type(config) is not dict or set(config) != required or config["enabled"] is not True:
        raise ValueError("execution not enabled by operator configuration")
    # Fresh independently published enrollment view must corroborate the host.
    inventory = node_registry_inventory.load()
    matches = [n for n in inventory["nodes"]
               if n["node"] == "gway-001" and n["registered"] is True
               and n["identity_verified"] is True and n["address"] == config["address"]
               and n["execute_eligible"] is True and n["reachable"] == "reachable"]
    if len(matches) != 1:
        raise PermissionError("node is not currently attested at pinned address")
    node = PinnedNode(node=config["node"],wireguard_address=config["address"],
                      ssh_host_alias=config["ssh_host_alias"],
                      known_hosts=Path(config["known_hosts"]),
                      identity_file=Path(config["identity_file"]),
                      host_key_sha256=config["host_key_sha256"],
                      remote_user=config["remote_user"])
    if node.node != matches[0]["node"]:
        raise PermissionError("node identity mismatch")
    ledger = RequestLedger()
    relay = DormantRelay(ledger, SSHTransport(node), enabled=True)
    return AuthorizedExecution(ledger, None, relay, enabled=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Operator-only execute token/approval; not an MCP tool")
    parser.add_argument("--issue-execute-token", action="store_true", required=True)
    parser.add_argument("--bearer-database", required=True)
    parser.add_argument("--lifetime", type=int, default=3600)
    args = parser.parse_args(argv)
    if args.issue_execute_token:
        if not args.bearer_database:
            parser.error("--bearer-database required to issue an execute token")
        from .mcp_bearer import BearerRegistry
        if not 60 <= args.lifetime <= 3600:
            parser.error("execute token lifetime must be 60..3600 seconds")
        token = BearerRegistry(args.bearer_database).issue(
            scope="gway:execute",lifetime=args.lifetime,operator_approved=True)
        # Intentionally printed only once in trusted local console.
        print(token)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
