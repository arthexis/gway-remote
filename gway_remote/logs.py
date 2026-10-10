"""Bounded, private installation logs and safe log export."""
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys

from .attempts import DEFAULT_DIR
from .reconcile import TARGETS

MAX_LOG_BYTES = 2 * 1024 * 1024
NAMES = frozenset(name for name, _ in TARGETS)
_SECRET = [
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)\S+"),
    re.compile(r"(?i)((?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]+)"),
    re.compile(r"(?i)((?:token|password|secret|api[_-]?key)\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@"),
]


def sanitize(value):
    value = value.replace("\x00", "")
    value = _SECRET[0].sub(r"\1[REDACTED]", value)
    value = _SECRET[1].sub("[REDACTED]", value)
    value = _SECRET[2].sub(r"\1[REDACTED]", value)
    return _SECRET[3].sub(r"\1[REDACTED]@", value)


def log_filename(name, sha):
    if name not in NAMES or not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise ValueError("invalid log identity")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{name}-{sha[:12].lower()}.log"


@contextmanager
def capture_log(directory, filename):
    """Capture subprocess stdout/stderr and Python output under the appliance lock.

    Log files are private. A crash still leaves the file for investigation.
    """
    path = Path(directory) / "logs"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    fd = os.open(path / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    saved_out, saved_err = os.dup(1), os.dup(2)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(fd, 1)
        os.dup2(fd, 2)
        try:
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(saved_out, 1)
            os.dup2(saved_err, 2)
    finally:
        os.close(fd)
        os.close(saved_out)
        os.close(saved_err)


def list_logs(directory=DEFAULT_DIR, name=None):
    if name is not None and name not in NAMES:
        raise ValueError("unknown component")
    folder = Path(directory) / "logs"
    if not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.iterdir()
         if p.is_file() and not p.is_symlink() and p.name.endswith(".log")
         and (name is None or f"-{name}-" in p.name)),
        reverse=True,
    )


def read_log(directory=DEFAULT_DIR, name=None, lines=100):
    if lines < 1 or lines > 10000:
        raise ValueError("lines must be between 1 and 10000")
    files = list_logs(directory, name)
    if not files:
        return None
    # Bounded reads even when the underlying installer produced excessive output.
    with files[0].open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - MAX_LOG_BYTES))
        content = handle.read(MAX_LOG_BYTES).decode("utf-8", errors="replace")
    return sanitize("\n".join(content.splitlines()[-lines:]))


def export_log(source, destination):
    """Produce a bounded, sanitized copy; never upload private raw logs."""
    with Path(source).open("rb") as handle:
        raw = handle.read(MAX_LOG_BYTES + 1)
    truncated = len(raw) > MAX_LOG_BYTES
    text = sanitize(raw[:MAX_LOG_BYTES].decode("utf-8", errors="replace"))
    if truncated:
        text += "\n[TRUNCATED: log exceeded 2 MiB]\n"
    Path(destination).write_text(text, encoding="utf-8")
