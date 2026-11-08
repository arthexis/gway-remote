"""Discover administratively installed node-owned MCP providers.

The installation directory is the authorization boundary: there is no separate
source approval registry. Repository checkouts are never scanned.
"""
import json
import os
from pathlib import Path

from .mcp_source_registry import SourceRegistration

INSTALL_DIR = "/etc/gway-mcp-providers"
MAX_MANIFEST_BYTES = 8192
MAX_PROVIDERS = 32
# Version 1 is the deployed on-disk contract.
MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FIELDS_V1 = frozenset({"source_id", "revision", "executable", "argv"})


def discover_installed_providers(directory=INSTALL_DIR):
    root = Path(directory)
    if not root.exists() and not root.is_symlink():
        return ()
    stat = root.lstat()
    if not root.is_dir() or root.is_symlink() or stat.st_uid != 0 or stat.st_mode & 0o022:
        raise ValueError("untrusted provider installation directory")
    registrations = []
    entries = sorted(path for path in root.iterdir() if path.suffix == ".json" and path.name != "agentops.runtime.json")
    if len(entries) > MAX_PROVIDERS:
        raise ValueError("too many installed providers")
    for path in entries:
        if path.suffix != ".json":
            continue
        info = path.lstat()
        if not path.is_file() or path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("untrusted provider manifest")
        if info.st_size > MAX_MANIFEST_BYTES:
            raise ValueError("oversized provider manifest")
        data = json.loads(path.read_bytes())
        if type(data) is not dict or set(data) != MANIFEST_FIELDS_V1:
            raise ValueError("invalid provider manifest")
        if path.stem != data["source_id"]:
            raise ValueError("provider manifest filename mismatch")
        executable = Path(data["executable"])
        # A managed release can be operator-owned; reject executables writable
        # by unrelated users, and never follow executable links.
        if executable.is_symlink() or not executable.is_file():
            raise ValueError("unsafe provider executable")
        executable_stat = executable.stat()
        if executable_stat.st_mode & 0o022 or not executable_stat.st_mode & 0o111:
            raise ValueError("unsafe provider executable")
        registrations.append(SourceRegistration(
            source_id=data["source_id"], revision=data["revision"],
            executable=data["executable"], argv=tuple(data["argv"]),
            run_as="arthe", enabled=True))
    if len({r.source_id for r in registrations}) != len(registrations):
        raise ValueError("duplicate installed provider")
    return tuple(registrations)
