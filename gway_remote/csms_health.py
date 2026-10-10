"""Read-only CSMS service and storage health; never probes OCPP sockets.

A healthy CSMS does not imply that charging is idle or that deployment is safe.
"""
import json
from pathlib import Path
import subprocess


def _run(argv, timeout=15):
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                timeout=timeout, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def csms_health(*, runner=_run, executable=None, data_dir=None):
    """Require active system service and valid read-only CSMS status contract."""
    executable = Path(executable) if executable is not None else Path.home() / ".local/bin/ocpp-csms"
    data_dir = Path(data_dir) if data_dir is not None else Path.home() / "ocpp-csms-data"
    if not executable.is_file() or not data_dir.is_dir():
        return False
    if runner(["systemctl", "is-active", "ocpp-csms.service"]) != "active":
        return False
    output = runner([str(executable), "--data-dir", str(data_dir), "status", "--json"])
    if output is None:
        return False
    try:
        document = json.loads(output)
    except (TypeError, ValueError):
        return False
    if not isinstance(document, dict) or document.get("schema") != "ocpp-csms/status/v1":
        return False
    data = document.get("data")
    if not isinstance(data, dict):
        return False
    server = data.get("server")
    storage = data.get("storage")
    if not isinstance(server, dict) or not isinstance(storage, dict):
        return False
    return (server.get("state") == "running" and
            storage.get("database") == "ok" and
            storage.get("transactions") == "ok")
