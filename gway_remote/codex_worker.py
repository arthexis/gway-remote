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
import logging


def default_socket() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "gway-codex-worker.sock"
    return Path.home() / ".local" / "state" / "gway-remote" / "codex-worker.sock"


def codex_available() -> bool:
    """Check executable presence without invoking Codex or reading credentials."""
    return shutil.which("codex") is not None


def status(started: float, *, executing: bool = False, task_id: str | None = None) -> dict:
    return {
        "service": "gway-codex-worker",
        "state": "executing" if executing else "idle",
        "active_task_id": task_id,
        "uptime_seconds": int(time.monotonic() - started),
        "codex_available": codex_available(),
        "task_execution_enabled": True,
    }


def serve(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Never delete an unknown socket or file: a second worker must not
    # displace a running daemon.
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"Socket path already exists: {path}")
    from .codex_queue import TaskQueue, default_db
    from .codex_reporting import ReportOutbox, record_interrupted
    with TaskQueue(default_db()) as queue:
        with ReportOutbox(default_db().with_suffix(".reports.sqlite")) as outbox:
            record_interrupted(queue, outbox)
    started = time.monotonic()
    stop = threading.Event()
    # Polling is enabled only when the worker has an explicitly provisioned
    # read-only GitHub token. Never log token contents.
    token = os.environ.get("GITHUB_TOKEN", "")
    interval = int(os.environ.get("GWAY_CODEX_POLL_SECONDS", "300"))
    if interval < 60:
        raise ValueError("poll interval must be at least 60 seconds")
    next_poll = time.monotonic() if token else float("inf")
    next_report_retry = time.monotonic()
    next_execution = time.monotonic()
    execution_lock = threading.Lock()
    execution_thread: threading.Thread | None = None
    active_task_id: str | None = None

    def execute_one() -> None:
        nonlocal active_task_id
        def on_claim(task_id: str) -> None:
            nonlocal active_task_id
            with execution_lock:
                active_task_id = task_id
        try:
            from .codex_executor import run_once
            run_once(token=token, on_claim=on_claim, stop=stop)
        except Exception as exc:
            logging.warning("Codex execution failed: %s", type(exc).__name__)
        finally:
            with execution_lock:
                active_task_id = None


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
                if token and time.monotonic() >= next_report_retry:
                    next_report_retry = time.monotonic() + interval
                    try:
                        from .codex_reporting import ReportOutbox
                        from .codex_queue import default_db
                        with ReportOutbox(default_db().with_suffix(".reports.sqlite")) as outbox:
                            outbox.deliver(token)
                    except Exception as exc:
                        logging.warning("Codex issue reporting retry failed: %s",
                                        type(exc).__name__)
                if token and time.monotonic() >= next_poll:
                    next_poll = time.monotonic() + interval
                    try:
                        from .codex_queue import TaskQueue, default_db
                        from .codex_discovery import discover
                        with TaskQueue(default_db()) as queue:
                            discover(queue, token)
                    except Exception as exc:
                        logging.warning("Codex discovery failed: %s", type(exc).__name__)
                if time.monotonic() >= next_execution:
                    next_execution = time.monotonic() + 5
                    if execution_thread is None or not execution_thread.is_alive():
                        execution_thread = threading.Thread(
                            target=execute_one, name="codex-executor", daemon=False
                        )
                        execution_thread.start()
                try:
                    client, _ = server.accept()
                except socket.timeout:
                    continue
                with client:
                    client.settimeout(2)
                    with execution_lock:
                        active = active_task_id
                    running = execution_thread is not None and execution_thread.is_alive()
                    client.sendall((json.dumps(status(
                        started, executing=running, task_id=active
                    )) + "\n").encode())
        finally:
            if execution_thread is not None:
                execution_thread.join()
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
