"""Read-only CSMS service and storage diagnostics; no OCPP socket traffic."""
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


def csms_probe(*, runner=_run, executable=None, data_dir=None):
    """Return a diagnostic reason, not just a misleading unhealthy boolean."""
    executable = Path(executable) if executable is not None else Path.home() / ".local/bin/ocpp-csms"
    data_dir = Path(data_dir) if data_dir is not None else Path.home() / "ocpp-csms-data"
    def result(healthy, reason):
        return {"healthy": healthy, "reason": reason,
                "executable": str(executable), "data_dir": str(data_dir)}
    if not executable.is_file():
        return result(False, "CLI missing at expected path")
    if not data_dir.is_dir():
        return result(False, "data directory missing")
    service = runner(["systemctl", "is-active", "ocpp-csms.service"])
    if service != "active":
        return result(False, "system service not active or unavailable")
    output = runner([str(executable), "--data-dir", str(data_dir), "status", "--json"])
    if output is None:
        return result(False, "CSMS status --json command failed")
    try:
        document = json.loads(output)
    except (TypeError, ValueError):
        return result(False, "CSMS status did not return JSON")
    if not isinstance(document, dict) or document.get("schema") != "ocpp-csms/status/v1":
        return result(False, "CSMS status schema mismatch")
    data = document.get("data")
    if not isinstance(data, dict):
        return result(False, "CSMS status data missing")
    server = data.get("server")
    storage = data.get("storage")
    if not isinstance(server, dict) or not isinstance(storage, dict):
        return result(False, "CSMS server or storage status missing")
    if server.get("state") != "running":
        return result(False, "CSMS server not running")
    if storage.get("database") != "ok":
        return result(False, "CSMS database not healthy")
    if storage.get("transactions") != "ok":
        return result(False, "CSMS transaction archive not healthy")
    return result(True, "CSMS service and storage healthy")


def csms_health(*, runner=_run, executable=None, data_dir=None):
    return csms_probe(runner=runner, executable=executable, data_dir=data_dir)["healthy"]
