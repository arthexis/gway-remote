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
    if config.is_symlink() or not config.is_file() or config.stat().st_mode & 0o022:
        raise ValueError("untrusted SSH configuration")
    if config.stat().st_uid != os.geteuid():
        raise ValueError("SSH configuration owner mismatch")
    try:
        effective = runner(["ssh", "-F", str(config), "-G", alias],
                           capture_output=True, text=True, timeout=8, check=True).stdout
        options = dict(line.split(None, 1) for line in effective.splitlines() if " " in line)
        if (options.get("hostname") != "gelectriic.com"
                or options.get("batchmode", "").lower() != "yes"
                or options.get("stricthostkeychecking", "").lower() != "yes"
                or options.get("userknownhostsfile") in (None, "/dev/null")
                or not options.get("identityfile")):
            raise ValueError("Watchtower SSH trust not configured")
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
