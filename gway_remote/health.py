"""Non-mutating appliance health probes.

These checks never start a charger session or change a systemd unit.
Runtime health is independent of attempted revision.
"""
from __future__ import annotations

from pathlib import Path
import json
import subprocess

from .csms_health import csms_health
from .probe_registry import probe_for

DEFAULT_STATE = Path.home() / ".local/state/gway-remote/installed"


def _command(argv, *, timeout=20):
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, check=False,
                              timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _reports_ready(executable: Path, *, timeout: int = 20) -> bool:
    """An exit-zero command alone is not evidence that Reports is ready.

    Unconfigured/offline roles are not made ready by a probe; no state is mutated.
    """
    try:
        result = subprocess.run(
            [str(executable), "status", "--json"],
            capture_output=True, text=True, check=False, timeout=timeout,
        )
        if result.returncode != 0:
            return False
        document = json.loads(result.stdout)
        if not isinstance(document, dict) or document.get("state") != "ready":
            return False
        return (isinstance(document.get("config"), dict)
                and document["config"].get("state") == "valid"
                and isinstance(document.get("warehouse"), dict)
                and document["warehouse"].get("state") == "ready")
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return False


def component_health(name: str) -> bool:
    """Check existing installations without changing their operational state."""
    home = Path.home()
    spec = probe_for(name)
    if spec.kind == "executable":
        executable = (home / spec.executable) if not spec.executable.startswith("/") else Path(spec.executable)
        if name == "ocpp-reports":
            return executable.is_file() and _reports_ready(executable)
        return executable.is_file() and _command([str(executable), "--help"])
    if spec.kind == "lcd":
        prefix = home / spec.release
        unit = home / ".config/systemd/user/gway-app-observer.service"
        observer = home / spec.executable
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
    if spec.kind == "systemd":
        return _command(["systemctl", "is-active", "--quiet", spec.service]) and _command(
            ["systemctl", "is-enabled", "--quiet", spec.service])
    if spec.kind == "csms":
        return csms_health()
    return None  # No probe contract: unknown, not unhealthy.




def quick_component_check(name: str):
    """Return lightweight evidence; quick checks never establish full health."""
    home = Path.home()
    spec = probe_for(name)
    if spec.kind == "executable":
        executable = (home / spec.executable) if not spec.executable.startswith("/") else Path(spec.executable)
        return "executable-present" if executable.is_file() else "executable-missing"
    if spec.kind == "lcd":
        prefix = home / spec.release
        observer = home / spec.executable
        unit = home / ".config/systemd/user/gway-app-observer.service"
        if not prefix.is_symlink() or not observer.is_file():
            return "installation-incomplete"
        if unit.exists():
            try:
                content = unit.read_text(encoding="utf-8")
            except OSError:
                return "unit-unreadable"
            if "--notification-mode shadow" not in content or "--no-processes" not in content:
                return "unit-configuration-mismatch"
        return "installation-present"
    if spec.kind == "systemd":
        link = home / spec.release
        return "release-present" if link.is_symlink() and link.exists() else "release-missing"
    if spec.kind == "csms":
        from .csms_health import csms_liveness
        return csms_liveness()
    return "unsupported"
