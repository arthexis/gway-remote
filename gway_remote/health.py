"""Non-mutating appliance health probes.

These checks never start a charger session or change a systemd unit.
Runtime health is independent of attempted revision.
"""
from __future__ import annotations

from pathlib import Path
import subprocess

from .csms_health import csms_health

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
        return csms_health()
    return False


