"""Local WireGuard registration endpoint configuration (not peer enrollment)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_ENDPOINT = "https://register.jelectric.com"


def config_path() -> Path:
    return Path(os.environ.get("GWAY_REMOTE_WIREGUARD_CONFIG",
                            str(Path.home() / ".config/gway-remote/wireguard.json")))


def normalize_endpoint(value: str) -> str:
    value = value.strip()
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/") or
            parsed.port not in (None, 443)):
        raise ValueError("registration endpoint must be a bare HTTPS origin")
    if parsed.hostname.lower() != "register.jelectric.com":
        raise ValueError("registration endpoint host is not allowlisted")
    return "https://" + parsed.hostname.lower()


def endpoint() -> dict:
    path = config_path()
    if not path.exists():
        return {"endpoint": DEFAULT_ENDPOINT, "configured": False}
    if path.is_symlink() or not path.is_file():
        raise ValueError("unsafe WireGuard endpoint config")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"endpoint"} or not isinstance(data["endpoint"], str):
        raise ValueError("invalid WireGuard endpoint config")
    return {"endpoint": normalize_endpoint(data["endpoint"]), "configured": True}


def set_endpoint(value: str) -> dict:
    normalized = normalize_endpoint(value)
    path = config_path()
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError("unsafe WireGuard endpoint config")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ValueError("unsafe WireGuard config directory")
    # Atomic replace: no partially written configuration on interruption.
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".wireguard-", delete=False) as handle:
        temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        json.dump({"endpoint": normalized}, handle)
        handle.write("\n")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"endpoint": normalized, "configured": True}
