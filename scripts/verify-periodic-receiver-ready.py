#!/usr/bin/env python3
"""Read-only preflight for an existing receiver package upgrade; no provisioning."""
import os
from pathlib import Path
import socket
import re
import sqlite3
import stat
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gway_remote.node_exec_identity import selected_user, state_dir, validated_account
from gway_remote.node_exec_contract import validate_command


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2 or socket.gethostname() != sys.argv[1]:
        raise SystemExit('exact local root operator required')
    node=sys.argv[1]
    validate_command(node,'hostname')
    user=selected_user()
    account=validated_account(user)
    if node == 'ocpp-abb-1':
        import json
        journal=Path('/var/lib/gway-abb-relay-provision.json')
        info=journal.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
            raise SystemExit('unsafe ABB provisioning receipt')
        data=json.loads(journal.read_text())
        if (data.get('state'),data.get('node'),data.get('user'),user)!=('complete',node,'ubuntu','ubuntu'):
            raise SystemExit('ABB relay not provisioned')
    root=Path('/opt/gway-remote')
    package=root/'gway_remote'
    target=package.resolve(strict=True)
    if not package.is_symlink() or target.parent.parent != root/'.package-releases' or not re.fullmatch(r"[a-f0-9]{64}",target.parent.name):
        raise SystemExit('existing content-addressed receiver required')
    # The actual layout is releases/<digest>/gway_remote.
    for path in (root,root/'.package-releases',target.parent,target):
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SystemExit('unsafe receiver package')
    directory=state_dir(user)
    info=directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != account.pw_uid or info.st_mode & 0o077:
        raise SystemExit('unsafe executor state')
    db=directory/'jobs.sqlite3'
    if os.path.lexists(db):
        info=db.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != account.pw_uid or info.st_mode & 0o077:
            raise SystemExit('unsafe job ledger')
        with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=3) as connection:
            connection.execute('PRAGMA query_only=ON')
            if connection.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]:
                raise SystemExit('receiver busy; defer update')
    print(user)


if __name__ == '__main__':
    main()
