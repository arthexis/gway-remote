"""Local-only export of Watchtower's existing SSH relay *client* public key.

This is not a host key, and it never creates, copies or prints a private key.
The output SHA-256 is the checksum of the canonical one-line public-key text,
including its final newline, for the gway-002 node-side staging procedure.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from .host_identity import validate_public_key
from .watchtower_exec_service import CONFIG

FIELDS = frozenset((
    "node", "address", "ssh_host_alias", "known_hosts", "identity_file",
    "host_key_sha256", "remote_user",
))
NODE = re.compile(r"gway-[0-9]{3}\Z")
MAX_CONFIG_BYTES = 4096
MAX_OUTPUT_BYTES = 2048


class RelayPublicKeyUnavailable(ValueError):
    """The installed relay identity cannot be safely exported."""


def _config_nodes(path):
    """Read only a pinned, root-controlled local configuration file."""
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != 0 or info.st_mode & 0o022
                or not 0 < info.st_size <= MAX_CONFIG_BYTES):
            raise RelayPublicKeyUnavailable("unsafe execute configuration")
        raw = os.read(fd, MAX_CONFIG_BYTES + 1)
        if len(raw) != info.st_size:
            raise RelayPublicKeyUnavailable("execute configuration changed")
    finally:
        os.close(fd)
    config = json.loads(raw)
    if type(config) is not dict or config.get("enabled") is not True:
        raise RelayPublicKeyUnavailable("execution configuration not enabled")
    if set(config) == {"enabled", "nodes"} and type(config["nodes"]) is list:
        nodes = config["nodes"]
    elif set(config) == FIELDS | {"enabled"}:
        nodes = [{k: config[k] for k in FIELDS}]
    else:
        raise RelayPublicKeyUnavailable("invalid execute configuration")
    if not 1 <= len(nodes) <= 32 or any(
            type(n) is not dict or set(n) != FIELDS for n in nodes):
        raise RelayPublicKeyUnavailable("invalid pinned nodes")
    return nodes


def _private_identity(path):
    """Open one existing private identity without following a symlink."""
    path = Path(path)
    if (not path.is_absolute() or ".." in path.parts
            or str(path) == "/"):
        raise RelayPublicKeyUnavailable("invalid relay identity path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_mode & 0o077 or not 0 < info.st_size <= 16384):
            raise RelayPublicKeyUnavailable("unsafe relay identity metadata")
        # Require all parent directories to be trusted and non-writable by
        # unrelated accounts. The file itself may belong to the gateway UID.
        for ancestor in path.parents:
            parent = ancestor.lstat()
            if (not stat.S_ISDIR(parent.st_mode)
                    or parent.st_mode & 0o022
                    or parent.st_uid not in (0, info.st_uid)):
                raise RelayPublicKeyUnavailable("unsafe relay identity parent")
        return fd
    except BaseException:
        os.close(fd)
        raise


def export_public_key(node, *, config=CONFIG, run=subprocess.run):
    """Return only the canonical public key and checksum for an existing node.

    Root-only local CLI call. No SSH connection, token, service or filesystem
    mutation. The SSH tool receives the already-validated file descriptor via
    procfs, not an operator-provided path to reopen.
    """
    if os.geteuid() != 0:
        raise RelayPublicKeyUnavailable("root required")
    if type(node) is not str or not NODE.fullmatch(node):
        raise RelayPublicKeyUnavailable("invalid node")
    matching = [n for n in _config_nodes(config) if n["node"] == node]
    if len(matching) != 1:
        raise RelayPublicKeyUnavailable("node is not configured uniquely")
    identity_path = matching[0]["identity_file"]
    if type(identity_path) is not str:
        raise RelayPublicKeyUnavailable("invalid relay identity path")

    fd = _private_identity(identity_path)
    try:
        try:
            result = run(
                ["/usr/bin/ssh-keygen", "-y", "-P", "",
                 "-f", "/proc/self/fd/" + str(fd)],
                capture_output=True, text=True, timeout=5,
                check=False, pass_fds=(fd,),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RelayPublicKeyUnavailable("public-key derivation unavailable") from exc
    finally:
        os.close(fd)

    if result.returncode != 0 or not isinstance(result.stdout, str):
        raise RelayPublicKeyUnavailable("public-key derivation failed")
    if len(result.stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise RelayPublicKeyUnavailable("oversized public-key output")
    lines = result.stdout.strip().splitlines()
    if len(lines) != 1 or len(lines[0].split()) not in (2, 3):
        raise RelayPublicKeyUnavailable("invalid public-key output")
    key = validate_public_key(" ".join(lines[0].split()[:2]))
    return {
        "node": node,
        "public_key": key,
        "sha256": hashlib.sha256((key + "\n").encode("ascii")).hexdigest(),
    }
