"""Durable per-component attempt journal, written before invoking an installer."""
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

from .reconcile import TARGETS

DEFAULT_DIR = Path.home() / ".local/state/gway-remote"
NAMES = frozenset(name for name, _ in TARGETS)


def read_attempts(directory=DEFAULT_DIR):
    """A corrupt journal fails closed rather than causing repeated installations."""
    path = Path(directory) / "attempts.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or any(
        name not in NAMES or not isinstance(item, dict) or
        not isinstance(item.get("sha"), str) for name, item in data.items()
    ):
        raise ValueError("invalid attempt journal")
    return data


def _save(directory, data):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=".attempts-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(filename, directory / "attempts.json")
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def mark(name, sha, status, directory=DEFAULT_DIR, error=None, log=None):
    if name not in NAMES or status not in ("started", "installed", "failed"):
        raise ValueError("invalid attempt")
    from .reconcile import _SHA
    if not _SHA.fullmatch(sha):
        raise ValueError("invalid revision")
    entries = read_attempts(directory)
    entries[name] = {"sha": sha.lower(), "status": status,
                     "at": datetime.now(timezone.utc).isoformat(),
                     **({"error": str(error)[:500]} if error else {}),
                     **({"log": log} if log else {})
    _save(directory, entries)


def attempted_shas(directory=DEFAULT_DIR):
    return {name: entry["sha"] for name, entry in read_attempts(directory).items()}
