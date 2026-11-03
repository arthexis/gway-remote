"""Read trusted Watchtower operator settings without modifying them."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

DEFAULT = Path("/etc/gway-remote/watchtower.json")
DEFAULT_WG_CONFIG = "/etc/wireguard/gway.conf"


def adopt_settings(path: Path = DEFAULT) -> dict:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Watchtower operator settings missing or unsafe")
    info = path.stat()
    if info.st_uid != 0 or not stat.S_ISREG(info.st_mode) or (info.st_mode & 0o077):
        raise PermissionError("Watchtower operator settings must be root-owned 0600")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("invalid Watchtower operator settings")
    result = {}
    for key in ("ledger", "network", "gateway"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Watchtower operator settings missing " + key)
        result[key] = value
    config = data.get("config", data.get("wireguard_config", DEFAULT_WG_CONFIG))
    if not isinstance(config, str) or not config.startswith("/"):
        raise ValueError("invalid Watchtower WireGuard configuration path")
    result["config"] = config
    return result
