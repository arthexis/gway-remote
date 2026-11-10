"""Root-pinned opt-in Watchtower execution and local credential issuance."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import stat

from . import node_registry_inventory
from .watchtower_exec_transport import RequestLedger, PinnedNode, SSHTransport, MultiNodeTransport, DormantRelay
from .watchtower_exec_auth import AuthorizedExecution

CONFIG = Path("/etc/gway-mcp/execute.json")


def load_service(path=CONFIG):
    info = Path(path).lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o022 or info.st_size > 4096):
        raise PermissionError("untrusted execution configuration")
    config = json.loads(Path(path).read_text())
    if type(config) is not dict or config.get("enabled") is not True:
        raise ValueError("execution not enabled by operator configuration")
    fields = {"node", "address", "ssh_host_alias", "known_hosts",
              "identity_file", "host_key_sha256"}
    if set(config) == fields | {"enabled"}:
        entries = [{key: config[key] for key in fields}]
    elif set(config) == {"enabled", "nodes"} and type(config["nodes"]) is list:
        entries = config["nodes"]
    else:
        raise ValueError("invalid execution configuration")
    if not 1 <= len(entries) <= 32:
        raise ValueError("invalid pinned node count")
    inventory = node_registry_inventory.load()
    transports = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != fields:
            raise ValueError("invalid pinned node entry")
        name = entry["node"]
        if type(name) is not str or name in transports:
            raise ValueError("duplicate or invalid pinned node")
        matches = [n for n in inventory["nodes"]
                   if n["node"] == name and n["registered"] is True
                   and n["identity_verified"] is True
                   and n["address"] == entry["address"]
                   and n["execute_eligible"] is True
                   and n["reachable"] == "reachable"]
        if len(matches) != 1:
            raise PermissionError("node is not currently attested at pinned address")
        # No caller/config-selected Unix account. Until enrollment attests an
        # installer identity, remote execution must fail closed.
        # A bare installer_user in the inventory is not authenticated evidence.
        # Require a ledger-derived binding to this exact attested host key.
        binding = matches[0].get("installer_binding")
        if (type(binding) is not dict or binding.get("source") != "enrollment-ledger"
                or binding.get("node") != name
                or binding.get("host_public_key") != entry["host_key_sha256"]
                or binding.get("state") != "active"):
            raise PermissionError("authenticated installer binding unavailable")
        installer = binding.get("user")
        if (type(installer) is not str or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", installer)
                or installer == "root"):
            raise PermissionError("attested installer identity unavailable")
        node = PinnedNode(node=name, wireguard_address=entry["address"],
                          ssh_host_alias=entry["ssh_host_alias"],
                          known_hosts=Path(entry["known_hosts"]),
                          identity_file=Path(entry["identity_file"]),
                          host_key_sha256=entry["host_key_sha256"],
                          installer_user=installer)
        if node.ssh_host_alias != name:
            raise PermissionError("SSH host alias must match enrolled node")
        transports[name] = SSHTransport(node)
    ledger = RequestLedger()
    relay = DormantRelay(ledger, MultiNodeTransport(transports), enabled=True)
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
