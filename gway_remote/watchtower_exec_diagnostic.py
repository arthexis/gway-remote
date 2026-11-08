"""Read-only, fail-closed Watchtower execution readiness evidence.

No SSH probe, token introspection, dispatch, permission change or secret output.
Unknown is deliberately different from healthy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
import stat

from . import node_registry_inventory

STAGES = ("auth_scope", "current_eligibility", "pinned_transport",
          "bridge_dispatch", "ssh_transport", "worker_readiness")


def diagnose(node: str, *, inventory=None, config=None):
    """Return only allowlisted stage statuses; never expose configuration."""
    if not isinstance(node, str) or not node_registry_inventory.NODE.fullmatch(node):
        raise ValueError("invalid node")
    result = {"node": node, "mode": "read_only", "stages": {s: "unknown" for s in STAGES}}
    rows = (inventory if inventory is not None else node_registry_inventory.load())["nodes"]
    matches = [row for row in rows if row.get("node") == node]
    if len(matches) != 1:
        result["stages"]["current_eligibility"] = "denied"
        return result
    row = matches[0]
    eligible = (row.get("registered") is True and
                row.get("identity_verified") is True and
                row.get("execute_eligible") is True and
                row.get("reachable") == "reachable")
    result["stages"]["current_eligibility"] = "pass" if eligible else "denied"
    # Configuration is only used to establish membership, never to report
    # hostnames, fingerprints, file paths, identities or credentials.
    if config is not None:
        entries = config.get("nodes")
        if entries is None and "node" in config:
            entries = [config]
        if config.get("enabled") is not True:
            result["stages"]["pinned_transport"] = "disabled"
        elif not isinstance(entries, list):
            result["stages"]["pinned_transport"] = "unknown"
        else:
            result["stages"]["pinned_transport"] = (
                "configured" if any(isinstance(x, dict) and x.get("node") == node
                                    for x in entries) else "missing")
    # These stages cannot be proved from the enrollment snapshot. Keep them
    # unknown rather than presenting configuration as successful execution.
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Safe, passive execution readiness")
    parser.add_argument("node")
    parser.add_argument("--execute-config", default="/etc/gway-mcp/execute.json")
    args = parser.parse_args(argv)
    # Missing/unreadable operator config is unknown, not proof of absence.
    config = None
    try:
        path = Path(args.execute_config)
        if not path.is_symlink() and path.is_file():
            # Never load_service here: it constructs transports and opens ledgers.
            st = path.lstat()
            if st.st_uid == 0 and stat.S_ISREG(st.st_mode) and not st.st_mode & 0o022 and st.st_size <= 4096:
                config = json.loads(path.read_text())
    except (OSError, ValueError, TypeError, KeyError):
        pass
    print(json.dumps(diagnose(args.node, config=config), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
