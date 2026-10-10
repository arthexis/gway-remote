"""Read-only verification of an explicitly attested installed revision.

An installation marker alone is not proof of health. Callers must additionally
supply a component-specific runtime check before a deployment can be recorded.
No marker is created by this module.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .reconcile import TARGETS

VALID_NAMES = frozenset(name for name, _ in TARGETS)
SHA = re.compile(r"[a-fA-F0-9]{40}\Z")


def installed_revision(name: str, directory: str | Path) -> str | None:
    """Read a revision attestation, rejecting unknown or malformed records."""
    if name not in VALID_NAMES:
        raise ValueError("unknown deployment target")
    path = Path(directory) / (name + ".json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(data, dict) or data.get("component") != name:
        return None
    revision = data.get("sha")
    if not isinstance(revision, str) or SHA.fullmatch(revision) is None:
        return None
    return revision.lower()


def verify_installed(name: str, sha: str, directory: str | Path, health_check) -> bool:
    """Require both an exact revision attestation and a passing health check."""
    if name not in VALID_NAMES or SHA.fullmatch(sha) is None:
        return False
    if installed_revision(name, directory) != sha.lower():
        return False
    return health_check(name) is True
