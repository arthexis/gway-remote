"""Root-only grant/revoke of execution eligibility in the authoritative enrollment DB.

Eligibility never authorizes a command by itself. The gateway additionally requires
an attested enrolled node, pinned SSH transport, execute bearer and one-use approval.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3

from .node_inspection import snapshot_from_path
from .node_registry_inventory import LEDGER, SNAPSHOT, build, publish

DDL = """CREATE TABLE IF NOT EXISTS execution_eligibility (
    device TEXT PRIMARY KEY REFERENCES devices(device),
    host_public_key TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL
)"""


def set_eligibility(node, enabled, *, ledger=LEDGER, operator="root"):
    if os.geteuid() != 0:
        raise PermissionError("Watchtower execution eligibility requires root")
    from .node_registry_inventory import NODE, _stamp
    if not isinstance(node, str) or not NODE.fullmatch(node):
        raise ValueError("invalid node")
    if type(enabled) is not bool:
        raise ValueError("invalid eligibility")
    path = Path(ledger)
    if path.is_symlink() or not path.is_file():
        raise PermissionError("unsafe enrollment ledger")
    with sqlite3.connect(path, timeout=15) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(DDL)
        device = db.execute("SELECT state FROM devices WHERE device=?", (node,)).fetchone()
        if device is None or device[0] != "active":
            raise PermissionError("node must be actively enrolled")
        identity = db.execute(
            "SELECT host_public_key, state, valid_until FROM host_identities WHERE device=?",
            (node,)).fetchone()
        if enabled:
            from datetime import datetime, timezone
            if not identity or identity[1] != "active" or datetime.fromisoformat(identity[2]) <= datetime.now(timezone.utc):
                raise PermissionError("verified active host identity required")
        host_key = identity[0] if identity else ""
        db.execute("""INSERT INTO execution_eligibility
            (device,host_public_key,enabled,updated_at,updated_by) VALUES(?,?,?,?,?)
            ON CONFLICT(device) DO UPDATE SET host_public_key=excluded.host_public_key,
              enabled=excluded.enabled,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
            (node,host_key,int(enabled),_stamp(),operator))
    return {"node":node,"eligible":enabled}


def main(argv=None):
    p=argparse.ArgumentParser(description="Root-only central execution eligibility")
    p.add_argument("action",choices=("grant","revoke","status"))
    p.add_argument("node")
    args=p.parse_args(argv)
    if os.geteuid()!=0:
        p.error("root required")
    if args.action=="status":
        from .node_registry_inventory import build
        rows=build()["nodes"]
        result=next((r for r in rows if r["node"]==args.node),None)
        if result is None:
            p.error("node not actively enrolled")
        print(json.dumps({"node":args.node,"eligible":result["execute_eligible"]}))
        return
    result=set_eligibility(args.node,args.action=="grant")
    # Re-publish after updating the *same* authoritative ledger.
    # A revoked grant must fail closed at dispatch even if the snapshot is stale;
    # the gateway checks the snapshot's 120s freshness and identity each time.
    publish(build(probe=True))
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
