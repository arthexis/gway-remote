"""Root-controlled installation identity; never select an MCP caller's UID."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import stat

IDENTITY_CONFIG = Path("/etc/gway-remote/executor-identity.json")
COMMON_PATH = "/usr/local/libexec/gway-remote-tools:/usr/local/bin:/usr/bin:/bin"


def selected_user(path=IDENTITY_CONFIG, *, hostname=None):
    """Require a root-owned, non-writable installation record; no fallback."""
    config = Path(path)
    info = config.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o022 or info.st_size > 1024):
        raise PermissionError("unsafe installation identity record")
    with config.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if type(payload) is not dict or set(payload) != {"user"}:
        raise ValueError("invalid installation identity record")
    user = payload["user"]
    if (type(user) is not str or not user or user == "root"
            or len(user) > 32):
        raise PermissionError("invalid installation user")
    try:
        account = pwd.getpwnam(user)
    except KeyError as exc:
        raise PermissionError("installation user unavailable") from exc
    if account.pw_uid == 0:
        raise PermissionError("root execution denied")
    return user


def state_dir(user):
    """Durable state in the installed account's own private state directory."""
    if user != selected_user():
        raise PermissionError("state identity mismatch")
    account = pwd.getpwnam(user)
    return Path(account.pw_dir) / ".local/state/gway-remote/exec"


def command_environment(user=None):
    """Bounded environment with no inherited SSH agent or caller variables."""
    chosen = selected_user()
    if user is not None and user != chosen:
        raise PermissionError("executor identity mismatch")
    account = pwd.getpwnam(chosen)
    if os.geteuid() != account.pw_uid:
        raise PermissionError("incorrect executor effective identity")
    return {"PATH": COMMON_PATH, "HOME": account.pw_dir,
            "USER": chosen, "LOGNAME": chosen, "LANG": "C.UTF-8"}
