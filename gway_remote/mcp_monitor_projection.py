"""Read a minimal, root-published Watchtower monitor result for authenticated MCP."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat

PUBLIC_STATE = Path('/var/lib/gway-mcp-monitor-public/status.json')
MAX_AGE_SECONDS = 180


def monitor_status(path=PUBLIC_STATE, *, now=None):
    """Only expose a fresh fixed health class; no logs or service metadata."""
    now = now or datetime.now(timezone.utc)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                    or info.st_mode & 0o022 or not 0 < info.st_size <= 1024):
                raise ValueError('untrusted monitor projection')
            data = json.loads(stream.read(1025))
        if (type(data) is not dict or set(data) != {'schema', 'observed_at', 'status'}
                or type(data['schema']) is not int or data['schema'] != 1
                or data['status'] not in ('ok', 'failed')):
            raise ValueError('invalid monitor projection')
        observed = datetime.fromisoformat(data['observed_at'])
        age = (now - observed).total_seconds()
        if observed.tzinfo is None or not 0 <= age <= MAX_AGE_SECONDS:
            raise ValueError('stale monitor projection')
        return {'status': data['status']}
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return {'status': 'unknown'}


def add_monitor_status(payload):
    if type(payload) is not dict:
        raise ValueError('invalid inventory')
    return {**payload, 'watchtower_monitor': monitor_status()}
