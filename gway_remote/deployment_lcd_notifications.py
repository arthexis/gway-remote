"""Identity-preserving deployment notification contract for the shared LCD."""
from __future__ import annotations
import hashlib
import json
import re
import socket

from .lcd_notification_contract import validate_notice

NODE = re.compile(r"(?:gway-[0-9]{3,}|ocpp-abb-1|gelectriic\.com)\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
EVENT = {
    "deploy-started": ("info", "DEPLOY_START", 15),
    "deploy-activated": ("info", "ACTIVATED", 30),
    "deploy-skipped": ("important", "ALREADY_CURRENT", 30),
    "deploy-verified": ("important", "HEALTH_VERIFIED", 30),
    "deploy-failed": ("error", "DEPLOY_FAILED", 120),
    "rollback-started": ("important", "ROLLBACK_START", 30),
    "rollback-verified": ("important", "ROLLBACK_OK", 30),
    "rollback-failed": ("critical", "ROLLBACK_FAILED", 120),
}


def document(repository, target_node, event, attempt_id, *, origin_node=None):
    if (type(repository) is not str or REPOSITORY.fullmatch(repository) is None
            or type(attempt_id) is not str or not attempt_id
            or len(attempt_id) > 256 or event not in EVENT):
        raise ValueError("invalid deployment notice identity")
    source = origin_node or socket.gethostname().split(".", 1)[0]
    if (type(source) is not str or not NODE.fullmatch(source)
            or type(target_node) is not str or not NODE.fullmatch(target_node)):
        raise ValueError("unknown deployment source or destination")
    severity, reason, lifetime = EVENT[event]
    episode_id = (attempt_id if re.fullmatch(r"[A-Za-z0-9:_-]{8,80}", attempt_id)
                  else hashlib.sha256(attempt_id.encode()).hexdigest()[:32])
    result = {
        "schema": "gway-notification/v1", "system": "deploy",
        "origin_node": source, "target_node": target_node,
        "subject": {"type": "repository", "repository": repository},
        "state": event, "severity": severity, "reason_code": reason,
        "episode_id": episode_id, "expires_in": lifetime,
    }
    return validate_notice(result)


def send(document, *, runner, home, timeout=10):
    from pathlib import Path
    import subprocess
    argv = [str(Path(home) / ".local/bin/lcd"), "notice",
            json.dumps(document, sort_keys=True, separators=(",", ":"))]
    try:
        result = runner(argv, timeout=timeout, check=False,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
