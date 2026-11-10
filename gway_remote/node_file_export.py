"""Bounded, read-only file export primitive for a future MCP node tool.

This module does not register an MCP route or grant remote file access.
"""
from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import stat
from pathlib import Path

MAX_FILE_BYTES = 3 * 1024 * 1024


def export_file(path: str, *, export_root: str, max_bytes: int = MAX_FILE_BYTES) -> dict:
    """Read one regular file beneath a trusted export root without following symlinks.

    The root must be provisioned by the operator, not supplied by an MCP caller.
    Only a single filename is accepted: no subdirectories or path traversal.
    """
    if type(path) is not str or not path or "/" in path or path in {".", ".."}:
        raise ValueError("invalid export filename")
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_FILE_BYTES:
        raise ValueError("invalid size limit")
    root = Path(export_root)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root_fd)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
                raise ValueError("not a bounded regular file")
            with os.fdopen(os.dup(fd), "rb") as stream:
                payload = stream.read(max_bytes + 1)
            after = os.fstat(fd)
            if (len(payload) > max_bytes or len(payload) != before.st_size
                    or before.st_dev != after.st_dev or before.st_ino != after.st_ino
                    or before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns):
                raise ValueError("file changed or exceeds limit")
        finally:
            os.close(fd)
    finally:
        os.close(root_fd)
    return {
        "filename": path,
        "mime_type": mimetypes.guess_type(path)[0] or "application/octet-stream",
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "encoding": "base64",
        "content": base64.b64encode(payload).decode("ascii"),
    }
