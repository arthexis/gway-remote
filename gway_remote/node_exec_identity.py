"""Root-controlled node execution identity and per-account runtime selection.

The MCP caller cannot choose the operating-system identity. Ansible provisions
the only supported override; missing configuration preserves gway-exec.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import socket
import stat

IDENTITY_CONFIG = Path("/etc/gway-remote/executor-identity.json")
DEFAULT_USER = "gway-exec"
OPERATOR_USER = "arthe"
OPERATOR_NODE = "gway-001"
DEFAULT_STATE_DIR = Path("/var/lib/gway-exec")
OPERATOR_STATE_DIR = Path("/var/lib/gway-remote-exec-arthe")
OPERATOR_AGENT = Path("/run/bastion-ssh/agent.sock")
COMMON_PATH = "/usr/local/libexec/gway-remote-tools:/usr/local/bin:/usr/bin:/bin"
OPERATOR_PATH = "/home/arthe/.local/bin:/home/arthe/.local/libexec:/usr/local/sbin:" + COMMON_PATH


def selected_user(path=IDENTITY_CONFIG, *, hostname=None):
    """Fail closed for invalid, writable or unexpected root-managed identity."""
    config = Path(path)
    try:
        info = config.lstat()
    except FileNotFoundError:
        return DEFAULT_USER
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o022):
        raise PermissionError("unsafe executor identity configuration")
    with config.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if type(payload) is not dict or set(payload) != {"user"}:
        raise ValueError("invalid executor identity configuration")
    user = payload["user"]
    host = hostname if hostname is not None else socket.gethostname()
    if user == DEFAULT_USER:
        return user
    if user == OPERATOR_USER and host == OPERATOR_NODE:
        return user
    raise PermissionError("executor identity not authorized for this node")


def state_dir(user):
    if user == DEFAULT_USER:
        return DEFAULT_STATE_DIR
    if user == OPERATOR_USER:
        return OPERATOR_STATE_DIR
    raise ValueError("unknown executor identity")


def command_environment(user=None):
    """Construct a minimal identity-specific child environment, no inherited secrets."""
    user = selected_user() if user is None else user
    account = pwd.getpwnam(user)
    if os.geteuid() != account.pw_uid:
        raise PermissionError("incorrect executor effective identity")
    env = {"PATH": OPERATOR_PATH if user == OPERATOR_USER else COMMON_PATH,
           "HOME": account.pw_dir, "USER": user, "LOGNAME": user,
           "LANG": "C.UTF-8"}
    if user == OPERATOR_USER:
        # Missing Bastion key is normal. Never connect through a user-supplied
        # socket or inherit SSH_AUTH_SOCK from the SSH relay environment.
        try:
            info = OPERATOR_AGENT.lstat()
            if (stat.S_ISSOCK(info.st_mode) and info.st_uid == account.pw_uid
                    and not info.st_mode & 0o077):
                env["SSH_AUTH_SOCK"] = str(OPERATOR_AGENT)
        except FileNotFoundError:
            pass
    return env
