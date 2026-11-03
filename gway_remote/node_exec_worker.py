"""Local-only M3 B2a job runner. NO network or MCP execution endpoint.

Invoke as dedicated unprivileged gway-exec user, with a working systemd --user
manager. Future Watchtower B2b transport must authenticate separately.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import pwd
import secrets
import signal
import sqlite3
import stat
import subprocess
import sys
import time

from .node_exec_contract import DEFAULT_LIMITS, validate_command, validate_transition

ACCOUNT = "gway-exec"
DEFAULT_STATE = Path("/var/lib/gway-exec/jobs.sqlite3")
MAX_OUTPUT = DEFAULT_LIMITS["max_output_bytes"]
MAX_ACTIVE = DEFAULT_LIMITS["concurrent_jobs_per_node"]
MAX_HISTORY = 256
RETENTION_DAYS = 7
JOB_TIMEOUT = DEFAULT_LIMITS["job_timeout_seconds"]


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def require_account(user=ACCOUNT):
    """Do not expose a privileged local command broker."""
    if os.geteuid() != pwd.getpwnam(user).pw_uid:
        raise PermissionError("executor must run as dedicated gway-exec user")


def unit_name(job_id):
    if len(job_id) != 32 or not all(c in "0123456789abcdef" for c in job_id):
        raise ValueError("invalid job ID")
    return "gway-exec-" + job_id + ".service"


class Jobs:
    def __init__(self, path=DEFAULT_STATE):
        self.path = Path(path)
        self._validate_dir()

    def _validate_dir(self):
        parent = self.path.parent
        mode = parent.lstat()
        if not stat.S_ISDIR(mode.st_mode) or mode.st_mode & 0o077 or mode.st_uid != os.geteuid():
            raise PermissionError("job storage directory must be owned by executor and mode 0700")
        if self.path.is_symlink():
            raise PermissionError("job database must not be symlink")

    @contextmanager
    def connection(self):
        self._validate_dir()
        if self.path.exists():
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise PermissionError("unsafe job database")
        old = os.umask(0o077)
        try:
            db = sqlite3.connect(self.path, timeout=5)
        finally:
            os.umask(old)
        db.row_factory = sqlite3.Row
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, node TEXT NOT NULL, command TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL,
                started_at TEXT, finished_at TEXT, exit_code INTEGER,
                output BLOB NOT NULL DEFAULT X'', truncated INTEGER NOT NULL DEFAULT 0,
                cancel_requested INTEGER NOT NULL DEFAULT 0
            )""")
            with db:
                yield db
        finally:
            db.close()

    def submit(self, node, command, *, execute=subprocess.run, python=sys.executable):
        validate_command(node, command)
        # Avoid fallback to root, system manager or a shell on the submitting host.
        require_account()
        job_id = secrets.token_hex(16)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            # Bound persistent metadata as well as each job's output spool.
            db.execute("DELETE FROM jobs WHERE status NOT IN ('queued','running') "
                       "AND created_at < ?",
                       ((datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat(),))
            count = db.execute("SELECT count(*) FROM jobs").fetchone()[0]
            if count >= MAX_HISTORY:
                raise RuntimeError("job history capacity exceeded")
            active = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            if active >= MAX_ACTIVE:
                raise RuntimeError("executor busy")
            db.execute("INSERT INTO jobs (id,node,command,status,created_at) VALUES (?,?,?,?,?)",
                       (job_id, node, command, "queued", utcnow()))
        # The systemd user manager does not inherit the caller's Python import
        # context. Use the Ansible-owned package tree, never a writable job dir.
        argv = ["systemd-run", "--user", "--collect",
                "--setenv=PYTHONPATH=/opt/gway-remote",
                "--working-directory=/var/lib/gway-exec",
                "--unit=" + unit_name(job_id),
                "--property=MemoryMax=" + str(DEFAULT_LIMITS["memory_max_bytes"]),
                "--property=TasksMax=" + str(DEFAULT_LIMITS["tasks_max"]),
                "--property=RuntimeMaxSec=" + str(JOB_TIMEOUT + 10),
                "--property=KillMode=control-group",
                python, "-m", "gway_remote.node_exec_worker", "--database", str(self.path),
                "--run", job_id]
        try:
            execute(argv, capture_output=True, text=True, check=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            with self.connection() as db:
                db.execute("UPDATE jobs SET status='failed', finished_at=? WHERE id=? AND status='queued'",
                           (utcnow(), job_id))
            raise RuntimeError("systemd user job launch failed") from None
        return job_id

    def row(self, job_id):
        unit_name(job_id)
        with self.connection() as db:
            record = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if record is None:
            raise ValueError("job not found")
        return dict(record)

    def result(self, job_id, cursor=0):
        if type(cursor) is not int or not 0 <= cursor <= MAX_OUTPUT:
            raise ValueError("invalid cursor")
        row = self.row(job_id)
        output = row["output"]
        chunk = output[cursor:cursor + DEFAULT_LIMITS["max_output_chunk_bytes"]]
        next_cursor = cursor + len(chunk)
        return {"schema": 1, "request_id": job_id, "node": row["node"],
                "status": row["status"], "stdout": chunk.decode("utf-8", errors="replace"),
                "stderr": "", "truncated": bool(row["truncated"]),
                "cursor": str(next_cursor) if next_cursor < len(output) else None,
                "exit_code": row["exit_code"], "started_at": row["started_at"],
                "finished_at": row["finished_at"]}

    def cancel(self, job_id, *, execute=subprocess.run):
        require_account()
        row = self.row(job_id)
        if row["status"] in ("succeeded", "failed", "cancelled", "timed_out", "unknown"):
            return row["status"]
        with self.connection() as db:
            db.execute("UPDATE jobs SET cancel_requested=1 WHERE id=? AND status IN ('queued','running')",
                       (job_id,))
        try:
            execute(["systemctl", "--user", "kill", "--kill-whom=all",
                     "--signal=SIGTERM", unit_name(job_id)],
                    check=True, capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            # Do not claim successful cancellation if service-manager kill fails.
            return "cancel_requested"
        return "cancel_requested"

    def reconcile(self, job_id, *, execute=subprocess.run):
        """Classify lost units after executor restart; never automatically rerun."""
        row = self.row(job_id)
        if row["status"] not in ("queued", "running"):
            return row["status"]
        try:
            p = execute(["systemctl", "--user", "show", unit_name(job_id),
                         "--property=ActiveState", "--value"],
                        capture_output=True, text=True, check=True, timeout=5)
            alive = p.stdout.strip() in ("active", "activating", "deactivating")
        except (OSError, subprocess.SubprocessError):
            # Transport/user manager unavailable: preserve current state.
            return row["status"]
        if alive:
            return row["status"]
        final = "cancelled" if row["cancel_requested"] else "unknown"
        with self.connection() as db:
            db.execute("UPDATE jobs SET status=?, finished_at=? WHERE id=? AND status IN ('queued','running')",
                       (final, utcnow(), job_id))
        return final


def _stop_group(process):
    # The child has a new session, and the systemd service has KillMode=control-group.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def worker(database, job_id):
    require_account()
    jobs = Jobs(database)
    row = jobs.row(job_id)
    if row["status"] != "queued":
        return 1
    with jobs.connection() as db:
        updated = db.execute("UPDATE jobs SET status='running', started_at=? WHERE id=? AND status='queued' AND cancel_requested=0",
                             (utcnow(), job_id)).rowcount
        if not updated:
            # A job cancelled before starting must never execute.
            db.execute("UPDATE jobs SET status='cancelled', finished_at=? WHERE id=? AND status='queued' AND cancel_requested=1",
                       (utcnow(), job_id))
            return 0
    # Capture into a bounded spool. No command output enters the service journal.
    output = bytearray()
    truncated = False
    try:
        process = subprocess.Popen(["/bin/sh", "-c", row["command"]],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True,
                                   env={"PATH": "/usr/local/bin:/usr/bin:/bin",
                                        "HOME": str(pwd.getpwuid(os.geteuid()).pw_dir),
                                        "LANG": "C.UTF-8"})
    except OSError:
        with jobs.connection() as db:
            db.execute("UPDATE jobs SET status='failed', finished_at=? WHERE id=? AND status='running'",
                       (utcnow(), job_id))
        return 1
    try:
        # readline can grow unbounded on no-newline output. Use bounded reads.
        import selectors
        sel = selectors.DefaultSelector()
        sel.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + JOB_TIMEOUT
        expired = False
        while True:
            if time.monotonic() >= deadline:
                expired = True
                _stop_group(process)
                break
            ready = sel.select(timeout=min(0.25, max(0, deadline - time.monotonic())))
            if ready:
                data = os.read(process.stdout.fileno(), 8192)
                if not data:
                    break
                remaining = MAX_OUTPUT - len(output)
                output.extend(data[:remaining])
                truncated |= len(data) > remaining
            elif process.poll() is not None:
                # Wait for EOF from any descendant that inherited stdout.
                continue
        if expired:
            state = "timed_out"
            code = None
        else:
            code = process.wait(timeout=2)
            state = "succeeded" if code == 0 else "failed"
    except (OSError, subprocess.SubprocessError):
        _stop_group(process)
        state, code = "failed", None
    finally:
        process.stdout.close()
    with jobs.connection() as db:
        item = db.execute("SELECT cancel_requested,status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if item["status"] == "running":
            if item["cancel_requested"]:
                state = "cancelled"
            validate_transition("running", state)
            db.execute("UPDATE jobs SET status=?, finished_at=?, exit_code=?, output=?, truncated=? WHERE id=? AND status='running'",
                       (state, utcnow(), code, bytes(output), int(truncated), job_id))
    return 0


def main():
    p = argparse.ArgumentParser(description="Local-only gway-exec worker; no MCP endpoint")
    p.add_argument("--database", default=str(DEFAULT_STATE))
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--run")
    group.add_argument("--status")
    group.add_argument("--cancel")
    args = p.parse_args()
    jobs = Jobs(args.database)
    if args.run:
        return worker(args.database, args.run)
    if args.cancel:
        print(jobs.cancel(args.cancel))
    else:
        jobs.reconcile(args.status)
        print(json.dumps(jobs.result(args.status), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
