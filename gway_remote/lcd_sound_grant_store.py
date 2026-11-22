"""Read-only operator-controlled grant snapshot for trusted LCD/Sound ingress.

No credentials or source secrets live in this file. The existing authenticated
ingress supplies verified principals separately. Never accept a path from an
external event, request parameter, or environment variable.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

POLICY_PATH = Path("/etc/gway-remote/lcd-sound-sources.json")
MAX_POLICY_BYTES = 16384


def load_operator_grants(path=POLICY_PATH, *, expected_owner=0):
    """Read an exact JSON grant snapshot; fail closed on unsafe file metadata."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise PermissionError("grant path not trusted")
    parent = path.parent
    parent_info = parent.lstat()
    if (not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != expected_owner
            or parent_info.st_mode & 0o022):
        raise PermissionError("grant directory not trusted")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != expected_owner
                or info.st_mode & 0o022 or info.st_nlink != 1
                or info.st_size > MAX_POLICY_BYTES):
            raise PermissionError("untrusted grant snapshot")
        raw = os.read(fd, MAX_POLICY_BYTES + 1)
        if len(raw) > MAX_POLICY_BYTES:
            raise PermissionError("grant snapshot oversized")
    finally:
        os.close(fd)
    value = json.loads(raw)
    if type(value) is not dict or set(value) != {"schema", "grants"}:
        raise ValueError("invalid grant snapshot schema")
    if type(value["schema"]) is not int or value["schema"] != 1:
        raise ValueError("unsupported grant schema")
    grants = value["grants"]
    if type(grants) is not dict or len(grants) > 64:
        raise ValueError("invalid grant registry")
    return grants
