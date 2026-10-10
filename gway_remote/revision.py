"""Exact installed revision evidence, never inferred from GitHub deployment history.

A marker is only accepted when the installed artifact itself identifies the same
full commit. Missing evidence fails closed. No marker is created by this module.
"""
from __future__ import annotations

import json
from pathlib import Path

from .installed import SHA, VALID_NAMES


def artifact_revision(name: str, home: Path | None = None) -> str | None:
    """Read the full SHA embedded in the currently activated artifact."""
    if name not in VALID_NAMES:
        raise ValueError("unknown deployment target")
    home = Path.home() if home is None else Path(home)
    if name == "gway-lcd-sound":
        current = home / ".local/share/gway-lcd-sound/current"
        if not current.is_symlink():
            return None
        source = current / ".gway-revision.json"
    elif name == "ocpp-simulator":
        source = home / ".local/share/ocpp-simulator/current/.gway-revision.json"
    else:
        source = home / ".local/share/ocpp-csms/current/.gway-revision.json"
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(data, dict) or data.get("component") != name:
        return None
    sha = data.get("sha")
    return sha.lower() if isinstance(sha, str) and SHA.fullmatch(sha) else None


def verified_revision(name: str, directory: Path, home: Path | None = None) -> str | None:
    """Require independent agreement between deployment marker and active artifact."""
    from .installed import installed_revision

    marker = installed_revision(name, directory)
    artifact = artifact_revision(name, home)
    return marker if marker is not None and marker == artifact else None
