"""User-bus launch regression for SSH/sudo execution.

The node protocol is invoked with a sparse environment. The job runner must
derive the bus from the effective executor UID rather than SSH-provided values.
"""
import os
from pathlib import Path
import pwd
import sqlite3
import stat
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gway_remote import node_exec_worker as worker


def test_manager_env_ignores_inherited_ssh_values():
    uid = 2244
    user = SimpleNamespace(pw_uid=uid, pw_name="gway-exec", pw_dir="/var/lib/gway-exec")
    directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=uid)
    bus = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=uid)
    with (patch.object(worker.os, "geteuid", return_value=uid),
          patch.object(worker.pwd, "getpwnam", return_value=user),
          patch.object(worker.pwd, "getpwuid", return_value=user),
          patch.object(Path, "lstat", side_effect=[directory, bus]),
          patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/tmp/attacker",
                                  "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/attacker/bus"})):
        env = worker.user_manager_env()
    assert env["XDG_RUNTIME_DIR"] == "/run/user/2244"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/2244/bus"
    assert env["HOME"] == "/var/lib/gway-exec"


def test_wrong_owner_bus_fails_closed():
    uid = 2244
    user = SimpleNamespace(pw_uid=uid, pw_name="gway-exec", pw_dir="/var/lib/gway-exec")
    directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=uid)
    bus = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=0)
    with (patch.object(worker.os, "geteuid", return_value=uid),
          patch.object(worker.pwd, "getpwnam", return_value=user),
          patch.object(worker.pwd, "getpwuid", return_value=user),
          patch.object(Path, "lstat", side_effect=[directory, bus])):
        with pytest.raises(RuntimeError, match="user manager unavailable"):
            worker.user_manager_env()


def test_launch_pins_bus_and_records_sanitized_error(tmp_path):
    tmp_path.chmod(0o700)
    seen = []
    def fake_run(argv, **kwargs):
        seen.append((argv, kwargs))
        raise subprocess.CalledProcessError(
            1, argv, stderr="Failed to connect to bus: No medium found; token SECRET"
        )

    with (patch.object(worker, "require_account"),
          patch.object(worker, "user_manager_env",
                       return_value={"XDG_RUNTIME_DIR": "/run/user/2244",
                                     "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/2244/bus"})):
        jobs = worker.Jobs(tmp_path / "jobs.sqlite3", max_active=1)
        with pytest.raises(RuntimeError, match="systemd user bus unavailable"):
            jobs.submit("gway-001", "hostname", request_id="a" * 32, execute=fake_run)
        result = jobs.result("a" * 32)

    assert seen[0][0][:2] == ["systemd-run", "--user"]
    assert seen[0][1]["env"]["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/2244/bus"
    assert result["status"] == "failed"
    assert result["stderr"] == "systemd user bus unavailable"
    assert "SECRET" not in str(result)
    assert result["exit_code"] is None


def test_launch_diagnostic_schema_migrates(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "jobs.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE jobs (
            id TEXT PRIMARY KEY, node TEXT NOT NULL, command TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL,
            started_at TEXT, finished_at TEXT, exit_code INTEGER,
            output BLOB NOT NULL DEFAULT X'', truncated INTEGER NOT NULL DEFAULT 0,
            cancel_requested INTEGER NOT NULL DEFAULT 0)""")
    path.chmod(0o600)
    with patch.object(worker, "require_account"):
        jobs = worker.Jobs(path, max_active=1)
        with jobs.connection() as db:
            assert "launch_diagnostic" in {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
