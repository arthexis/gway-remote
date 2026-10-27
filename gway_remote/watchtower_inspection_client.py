"""Authenticated, bounded read-only Watchtower snapshot retrieval over existing SSH."""
import json
import subprocess
from pathlib import Path

from .node_inspection import resolve_target

SSH_CONFIG = Path("/etc/gway-remote/inspection-ssh.conf")
WATCHTOWER_ALIAS = "gelectriic.com"


def fetch_snapshot(*, config=SSH_CONFIG, alias=WATCHTOWER_ALIAS, command=None,
                   runner=subprocess.run):
    """SSH transport requires a separately approved, read-only server command.

    No shell expansion or public HTTP enrollment endpoint is used. The server
    must restrict this identity to the root-owned snapshot export (ForceCommand
    or equivalent). SSH host keys must be independently pinned by Bastion.
    """
    if alias != WATCHTOWER_ALIAS:
        raise ValueError("unapproved Watchtower alias")
    config = Path(config)
    if config.is_symlink() or not config.is_file() or config.stat().st_mode & 0o022:
        raise ValueError("untrusted SSH configuration")
    # This command is fixed; deployment must configure a forced-command key on
    # Watchtower, because the registry ledger is root-owned.
    argv = ["ssh", "-F", str(config), "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=8",
            alias, "gway-remote", "watchtower", "snapshot"]
    try:
        result = runner(argv, capture_output=True, text=True, timeout=15, check=True)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise ValueError("authenticated Watchtower registry unavailable") from exc
    if len(result.stdout) > 65536:
        raise ValueError("Watchtower snapshot too large")
    try:
        snapshot = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Watchtower snapshot") from exc
    return snapshot
