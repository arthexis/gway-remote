"""Pinned root-owned release metadata for HTTPS node bootstrap."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat

from .watchtower_relay_public_key import export_public_key

RELEASE_MARKER = Path("/opt/gway-remote-watchtower/bootstrap-release.sha")
SHA = re.compile(r"[0-9a-f]{40}\Z")


class ReleaseUnavailable(ValueError):
    """A reviewed bootstrap release or public identity is unavailable."""


def _root_owned_revision(path=RELEASE_MARKER):
    if os.geteuid() != 0:
        raise ReleaseUnavailable("root-owned release required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_nlink != 1 or info.st_mode & 0o022
                or not 40 <= info.st_size <= 42):
            raise ReleaseUnavailable("unsafe release marker")
        text = os.read(fd, 64).decode("ascii").strip()
    finally:
        os.close(fd)
    if not SHA.fullmatch(text):
        raise ReleaseUnavailable("invalid release revision")
    return text


def artifacts(*, marker=RELEASE_MARKER, client_path=None, relay=export_public_key):
    """Return only vetted public metadata; never a private key or URL bearer."""
    revision = _root_owned_revision(marker)
    path = Path(__file__).with_name("wireguard_satellite.py") if client_path is None else Path(client_path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_nlink != 1 or info.st_mode & 0o022
                or not 1024 < info.st_size < 1048576):
            raise ReleaseUnavailable("unsafe standalone client")
        content = os.read(fd, 1048576)
        if len(content) != info.st_size:
            raise ReleaseUnavailable("standalone client changed")
    finally:
        os.close(fd)
    key = relay("gway-001")["public_key"]
    if not isinstance(key, str) or not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]{40,128}", key):
        raise ReleaseUnavailable("existing relay public identity unavailable")
    return {"revision": revision,
            "client_sha256": hashlib.sha256(content).hexdigest(),
            "relay_public_key": key}
