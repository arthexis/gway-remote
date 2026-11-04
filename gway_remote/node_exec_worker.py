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
# Fixed cap protects memory on large hosts; configurable per-node below.
MAX_ACTIVE_CEILING = 8
EXECUTOR_CONFIG = Path("/etc/gway-remote/executor.json")
MAX_HISTORY = 256
RETENTION_DAYS = 7
JOB_TIMEOUT = DEFAULT_LIMITS["job_timeout_seconds"]


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def require_account(user=ACCOUNT):
    """Do not expose a privileged local command broker."""
    if os.geteuid() != pwd.getpwnam(user).pw_uid:
        raise PermissionError("executor must run as dedicated gway-exec user")


def user_manager_env():
    """Build a trusted user-bus environment, never from SSH/sudo input."""
    require_account()
    uid = os.geteuid()
    account = pwd.getpwuid(uid)
    runtime = Path("/run/user") / str(uid)
    try:
        info = runtime.lstat()
        bus = (runtime / "bus").lstat()
    except FileNotFoundError:
        raise RuntimeError("executor user manager unavailable") from None
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
            or info.st_mode & 0o022
            or not stat.S_ISSOCK(bus.st_mode) or bus.st_uid != uid):
        raise RuntimeError("executor user manager unavailable")
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": account.pw_dir,
        "USER": account.pw_name,
        "LOGNAME": account.pw_name,
        "LANG": "C.UTF-8",
        "XDG_RUNTIME_DIR": str(runtime),
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + str(runtime / "bus"),
    }


def launch_failure(exc):
    """Return fixed, non-sensitive error categories, never subprocess stderr."""
    stderr = getattr(exc, "stderr", None)
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    if isinstance(stderr, str) and (
            "Failed to connect to bus" in stderr or "No medium found" in stderr):
        return "systemd user bus unavailable"
    if isinstance(stderr, str) and "Failed to start transient service unit" in stderr:
        return "systemd transient unit rejected"
    if isinstance(exc, subprocess.TimeoutExpired):
        return "systemd launch timeout"
    if isinstance(exc, FileNotFoundError):
        return "systemd launcher missing"
    return "systemd launch failed"


def configured_max_active(path=EXECUTOR_CONFIG):
    """Use detected core count by default, with a safe root-controlled override."""
    detected = min(MAX_ACTIVE_CEILING, max(1, (os.cpu_count() or 1) - 1))
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return detected
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o022):
        raise PermissionError("unsafe executor configuration")
    with path.open(encoding="utf-8") as stream:
        config = json.load(stream)
    if type(config) is not dict or set(config) != {"max_active"}:
        raise ValueError("invalid executor configuration")
    value = config["max_active"]
    if value == "auto":
        return detected
    if type(value) is not int or not 1 <= value <= MAX_ACTIVE_CEILING:
        raise ValueError("invalid executor concurrency")
    return value


def validate_request_id(request_id):
    if (type(request_id) is not str or len(request_id) != 32
            or any(c not in "0123456789abcdef" for c in request_id)):
        raise ValueError("invalid request ID")
    return request_id


def unit_name(job_id):
    if len(job_id) != 32 or not all(c in "0123456789abcdef" for c in job_id):
        raise ValueError("invalid job ID")
    return "gway-exec-" + job_id + ".service"


class Jobs:
    def __init__(self, path=DEFAULT_STATE, *, max_active=None):
        self.path = Path(path)
        if max_active is None:
            max_active = configured_max_active()
        if type(max_active) is not int or not 1 <= max_active <= MAX_ACTIVE_CEILING:
            raise ValueError("invalid executor concurrency")
        self.max_active = max_active
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
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                launch_diagnostic TEXT NOT NULL DEFAULT \'\'
            )""")
            if "launch_diagnostic" not in {row[1] for row in db.execute("PRAGMA table_info(jobs)")}: 
                db.execute("ALTER TABLE jobs ADD COLUMN launch_diagnostic TEXT NOT NULL DEFAULT \'\'")
            with db:
                yield db
        finally:
            db.close()

    def submit(self, node, command, *, request_id=None, execute=subprocess.run, python=sys.executable):
        validate_command(node, command)
        # Avoid fallback to root, system manager or a shell on the submitting host.
        require_account()
        # The upstream relay owns a stable request ID across retries. Reusing
        # it with different command bytes/node is an error, never another job.
        job_id = validate_request_id(request_id) if request_id is not None else secrets.token_hex(16)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT node, command FROM jobs WHERE id=?", (job_id,)).fetchone()
            if existing is not None:
                if existing["node"] != node or existing["command"] != command:
                    raise ValueError("request ID conflict")
                return job_id
            # Bound persistent metadata as well as each job's output spool.
            db.execute("DELETE FROM jobs WHERE status NOT IN ('queued','running') "
                       "AND created_at < ?",
                       ((datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat(),))
            count = db.execute("SELECT count(*) FROM jobs").fetchone()[0]
            if count >= MAX_HISTORY:
                raise RuntimeError("job history capacity exceeded")
            # One local DB belongs to one executor appliance. Count globally
            # so changing a caller-supplied node string cannot bypass the cap.
            active = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            if active >= self.max_active:
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
            env = user_manager_env()
            execute(argv, capture_output=True, text=True, check=True, timeout=10, env=env)
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            diagnostic = launch_failure(exc)
            if isinstance(exc, RuntimeError):
                diagnostic = "executor user manager unavailable"
            with self.connection() as db:
                db.execute("UPDATE jobs SET status='failed', finished_at=?, launch_diagnostic=? WHERE id=? AND status='queued'",
                           (utcnow(), diagnostic, job_id))
            raise RuntimeError(diagnostic) from None
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
                "stderr": row["launch_diagnostic"], "truncated": bool(row["truncated"]),
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
            execute(["systemctl", "--user", "kill", "--kill-whom=main",
                     "--signal=SIGUSR1", unit_name(job_id)],
                    check=True, capture_output=True, timeout=5, env=user_manager_env())
        except (OSError, subprocess.SubprocessError, RuntimeError):
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
                        capture_output=True, text=True, check=True, timeout=5,
                        env=user_manager_env())
            alive = p.stdout.strip() in ("active", "activating", "deactivating")
        except (OSError, subprocess.SubprocessError, RuntimeError):
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
            # The cancel caller persists intent before notifying this worker.
            # Never kill the worker itself: it must record the terminal state.
            if jobs.row(job_id)["cancel_requested"]:
                _stop_group(process)
                break
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
        elif jobs.row(job_id)["cancel_requested"]:
            state = "cancelled"
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
        # SIGUSR1 is a wake-up hint (not a termination signal); the durable
        # SQLite cancellation flag is authoritative and polled by the worker.
        # This keeps the worker alive to kill its child group and save result.
        signal.signal(signal.SIGUSR1, lambda _signum, _frame: None)
        return worker(args.database, args.run)
    if args.cancel:
        print(jobs.cancel(args.cancel))
    else:
        jobs.reconcile(args.status)
        print(json.dumps(jobs.result(args.status), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
