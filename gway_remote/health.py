"""Non-mutating appliance health probes.

These checks never start a charger session or change a systemd unit.
Revision identity is independently required by verify_installed().
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

from .installed import verify_installed

DEFAULT_STATE = Path.home() / ".local/state/gway-remote/installed"


def _command(argv, *, timeout=20):
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, check=False,
                              timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def component_health(name: str) -> bool:
    """Check existing installations without changing their operational state."""
    home = Path.home()
    if name == "ocpp-simulator":
        executable = home / ".local/bin/ocpp-simulator"
        return executable.is_file() and _command([str(executable), "--help"])
    if name == "gway-lcd-sound":
        prefix = home / ".local/share/gway-lcd-sound/current"
        unit = home / ".config/systemd/user/gway-app-observer.service"
        observer = home / ".local/bin/gway-app-observer"
        if not prefix.is_symlink() or not observer.is_file():
            return False
        if unit.exists():
            try:
                content = unit.read_text(encoding="utf-8")
            except OSError:
                return False
            if "--notification-mode shadow" not in content or "--no-processes" not in content:
                return False
        return _command([str(observer), "--help"])
    if name == "ocpp-csms":
        # Do not treat an installed CLI as proof that the live CSMS is healthy.
        # Requires a separately established service and traffic-safe probe.
        return False
    return False


def verify_component(name: str, sha: str, directory=DEFAULT_STATE) -> bool:
    return verify_installed(name, sha, directory, component_health)
