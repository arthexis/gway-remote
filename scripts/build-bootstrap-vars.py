#!/usr/bin/env python3
"""Emit bounded, nonsecret Ansible vars for the reviewed HTTPS bootstrap.

Run from a pinned clean checkout. All dangerous identity decisions reuse the
standalone client's root-owned policy and verified sudo-origin contract.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gway_remote.wireguard_satellite import resolve_executor_user, sudo_install_user


NODE = re.compile(r"gway-[0-9]{3}\Z")
REV = re.compile(r"[0-9a-f]{40}\Z")
PUBLIC = re.compile(r"ssh-ed25519 [A-Za-z0-9+/=]{40,128}\Z")
DENIED = {"root", "gway-exec", "gway-relay"}


def _relay_public_key(path):
    path = Path(path)
    parent = path.parent.lstat()
    if (not path.is_absolute() or ".." in path.parts
            or not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0
            or (parent.st_mode & 0o077)):
        raise PermissionError("relay key directory must be private and root-owned")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_nlink != 1 or (info.st_mode & 0o077)
                or not 40 < info.st_size < 512):
            raise PermissionError("untrusted relay public key artifact")
        value = os.read(fd, 512).decode("ascii").strip()
    finally:
        os.close(fd)
    if not PUBLIC.fullmatch(value):
        raise ValueError("invalid relay public key")
    return value


def variables(node, revision, relay_file, override="", *, environ=None,
              public_key_reader=_relay_public_key, user_resolver=resolve_executor_user,
              sudo_user_reader=sudo_install_user):
    if not NODE.fullmatch(node) or not REV.fullmatch(revision):
        raise ValueError("invalid node or immutable release")
    key = public_key_reader(relay_file)
    if not PUBLIC.fullmatch(key):
        raise ValueError("invalid relay public key")
    installer = sudo_user_reader(environ)
    selected = user_resolver(installer, override)
    runner = installer or selected
    if runner in DENIED or not re.fullmatch(r"[a-z_][a-z0-9_-]*", runner):
        raise PermissionError("an existing non-root installer is required")
    return {
        "gway_bootstrap_node": node,
        "gway_bootstrap_revision": revision,
        "gway_bootstrap_installer": runner,
        "gway_bootstrap_executor_override": override,
        "gway_bootstrap_relay_key_file": str(relay_file),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build nonsecret local bootstrap vars")
    parser.add_argument("--node", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--relay-key-file", type=Path, required=True)
    parser.add_argument("--executor-user", default="")
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.exit(1, "bootstrap vars denied: root_required\n")
    try:
        print(json.dumps(variables(args.node, args.revision, args.relay_key_file,
                                   args.executor_user), sort_keys=True))
    except (OSError, ValueError, PermissionError, TypeError):
        parser.exit(1, "bootstrap vars denied: invalid_identity_or_release\n")


if __name__ == "__main__":
    main()
