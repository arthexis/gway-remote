"""Idle, unprivileged Codex worker foundation.

No tasks are accepted or executed in chunk one. The daemon provides a local,
read-only health endpoint over a user-owned Unix domain socket.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import threading
import time


def default_socket() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "gway-codex-worker.sock"
    return Path.home() / ".local" / "state" / "gway-remote" / "codex-worker.sock"


def codex_available() -> bool:
    """Check executable presence without invoking Codex or reading credentials."""
    return shutil.which("codex") is not None


def status(started: float) -> dict:
    return {
        "service": "gway-codex-worker",
        "state": "idle",
        "uptime_seconds": int(time.monotonic() - started),
        "codex_available": codex_available(),
        "task_execution_enabled": False,
    }


def serve(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Never delete an unknown socket or file: a second worker must not
    # displace a running daemon.
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"Socket path already exists: {path}")
    started = time.monotonic()
    stop = threading.Event()

    def shutdown(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        old_umask = os.umask(0o177)
        try:
            server.bind(str(path))
        finally:
            os.umask(old_umask)
        server.listen(4)
        server.settimeout(0.5)
        try:
            while not stop.is_set():
                try:
                    client, _ = server.accept()
                except socket.timeout:
                    continue
                with client:
                    client.settimeout(2)
                    client.sendall((json.dumps(status(started)) + "\n").encode())
        finally:
            path.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GWAY Codex idle worker")
    parser.add_argument("action", choices=("serve", "status"))
    parser.add_argument("--socket", type=Path, default=default_socket())
    args = parser.parse_args(argv)
    if args.action == "serve":
        serve(args.socket)
        return 0
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        try:
            client.connect(str(args.socket))
            data = client.recv(4096)
        except (OSError, TimeoutError) as exc:
            parser.exit(1, f"Worker unavailable: {exc}\n")
    print(data.decode().strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
