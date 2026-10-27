"""Bounded Watchtower registry retrieval through a pinned SSH management identity."""
import json
import os
import subprocess
from pathlib import Path

SSH_CONFIG = Path("/etc/gway-remote/inspection-ssh.conf")
WATCHTOWER_ALIAS = "watchtower-inspection"


def fetch_snapshot(*, config=SSH_CONFIG, alias=WATCHTOWER_ALIAS, runner=subprocess.run):
    """Use a dedicated Bastion-provisioned forced-command SSH identity.

    Watchtower must constrain this identity to snapshot export; neither a
    general-purpose shell nor public enrollment HTTP is acceptable.
    """
    if alias != WATCHTOWER_ALIAS:
        raise ValueError("unapproved Watchtower inspection alias")
    config = Path(config)
    from .inspection_ssh_trust import validate_profile
    validate_profile(config, alias, hostname="gelectriic.com", runner=runner)
    try:
        result = runner(
            ["ssh", "-F", str(config), "-o", "BatchMode=yes",
             "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=8",
             alias, "snapshot"],
            capture_output=True, text=True, timeout=15, check=True,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise ValueError("authenticated Watchtower registry unavailable") from exc
    if len(result.stdout) > 65536:
        raise ValueError("Watchtower snapshot too large")
    try:
        snapshot = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Watchtower snapshot") from exc
    if not isinstance(snapshot, dict):
        raise ValueError("invalid Watchtower snapshot")
    return snapshot
