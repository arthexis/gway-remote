"""Emit only the local WireGuard public key, never private configuration."""
from __future__ import annotations

import base64
import subprocess


def public_key(interface: str = "gway", runner=subprocess.run) -> str:
    if interface != "gway":
        raise ValueError("unsupported WireGuard interface")
    try:
        result = runner(["wg", "show", interface, "public-key"], check=True,
                        capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("unable to inspect local WireGuard interface") from exc
    key = result.stdout.strip()
    try:
        if len(base64.b64decode(key, validate=True)) != 32:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid local WireGuard public key") from exc
    return key
