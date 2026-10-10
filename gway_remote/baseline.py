"""Read-only Gway-001 baseline; never deploys or starts services."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from .reconcile import TARGETS


def command(argv, timeout=8):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                check=False)
        return {"ok": result.returncode == 0,
                "value": result.stdout.strip()[:300] if result.returncode == 0 else None}
    except (OSError, subprocess.TimeoutExpired):
        return {"ok": False, "value": None}


def baseline():
    home = Path.home()
    state = home / ".local/state/gway-remote/installed"
    disk = shutil.disk_usage(home)
    data = {
        "node": os.uname().nodename,
        "time_unix": int(time.time()),
        "disk_free_bytes": disk.free,
        "memory_available_kib": None,
        "targets": {},
        "services": {},
        "active_transactions": "not-measured",
    }
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                data["memory_available_kib"] = int(line.split()[1])
                break
    except (OSError, ValueError):
        pass
    for name, _ in TARGETS:
        data["targets"][name] = {"health": "not-checked"}
    # Only query service state, never invoke start, restart or reload.
    for unit in ("ocpp-csms.service", "ocpp-discover.service"):
        data["services"][unit] = command(["systemctl", "--user", "is-active", unit])
    data["lcd_observer"] = command(
        ["systemctl", "--user", "is-active", "gway-app-observer.service"])
    data["simulator_cli"] = {
        "present": (home / ".local/bin/ocpp-simulator").is_file()
    }
    return data


def main():
    print(json.dumps(baseline(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
