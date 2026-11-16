"""Host-local owner flock primitive (V1). Not wired into any deploy entrypoint.

A trusted supervisor must keep this context alive through all effects, cleanup,
and verification. This module deliberately neither launches installers nor
claims that killing a process leader proves its descendants have terminated.
See docs/maintenance-lock-v1.md before adopting it in a runtime path.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import pwd
import stat
import time

TARGET_SECONDS = 180
TOTAL_SECONDS = 300
MAX_WAIT_SECONDS = 20
LOCK_NAME = "maintenance.lock"
UNCERTAIN_NAME = "maintenance.uncertain"
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC


class MaintenanceError(RuntimeError):
    """Sanitized error: no path, environment, account, or token disclosure."""

    exit_code = 2


class Busy(MaintenanceError):
    exit_code = 3

    def __init__(self):
        super().__init__("maintenance_busy")


class Invalid(MaintenanceError):
    def __init__(self):
        super().__init__("maintenance_invalid")


class Uncertain(MaintenanceError):
    exit_code = 125

    def __init__(self):
        super().__init__("maintenance_uncertain")


class TimedOut(MaintenanceError):
    exit_code = 124

    def __init__(self):
        super().__init__("maintenance_timeout")


def _directory_ok(fd: int, uid: int, *, private: bool = False, home: bool = False) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):
        raise Invalid()
    if home and info.st_uid != uid:
        raise Invalid()
    if not home and info.st_uid not in (0, uid):
        raise Invalid()
    if private:
        if info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
            raise Invalid()
    elif info.st_mode & 0o022:
        # The root-owned, sticky /tmp ancestor is safe to traverse with dirfds.
        if info.st_uid != 0 or info.st_mode & stat.S_ISVTX == 0:
            raise Invalid()


def _home_fd(uid: int) -> int:
    home = Path(pwd.getpwuid(uid).pw_dir)
    if not home.is_absolute() or home == Path("/") or ".." in home.parts:
        raise Invalid()
    fd = os.open("/", _DIRECTORY_FLAGS)
    try:
        _directory_ok(fd, uid)
        for segment in home.parts[1:]:
            next_fd = os.open(segment, _DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            _directory_ok(fd, uid)
        _directory_ok(fd, uid, home=True)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _child_dir(parent_fd: int, name: str, uid: int, *, private: bool) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
    try:
        _directory_ok(fd, uid, private=private, home=not private)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _same_inode(fd: int, directory_fd: int) -> None:
    current = os.fstat(fd)
    named = os.stat(LOCK_NAME, dir_fd=directory_fd, follow_symlinks=False)
    if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or
            (current.st_dev, current.st_ino) != (named.st_dev, named.st_ino) or
            not stat.S_ISREG(named.st_mode)):
        raise Invalid()


def _no_uncertain(directory_fd: int) -> None:
    try:
        os.stat(UNCERTAIN_NAME, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise Uncertain()


def _operator_uid() -> int:
    uid = os.geteuid()
    if uid == 0:
        raise Invalid()
    return uid


class MaintenanceLock:
    """Single-acquisition owner lock. Keep the returned context with the supervisor.

    Exposes the held file descriptor for **trusted** subprocess pass_fds; a
    matching fd/inode in an untrusted request is not proof of lock ownership.
    Do not reacquire in a nested installer.
    """

    def __init__(self, *, wait_seconds: float = MAX_WAIT_SECONDS):
        if type(wait_seconds) not in (float, int) or not 0 <= wait_seconds <= MAX_WAIT_SECONDS:
            raise Invalid()
        self.wait_seconds = wait_seconds
        self.started: float | None = None
        self._state_fd: int | None = None
        self._lock_fd: int | None = None

    def __enter__(self) -> "MaintenanceLock":
        if self._state_fd is not None or self._lock_fd is not None:
            raise Invalid()
        self.started = time.monotonic()
        uid = _operator_uid()
        try:
            home_fd = _home_fd(uid)
            try:
                local_fd = _child_dir(home_fd, ".local", uid, private=False)
                try:
                    self._state_fd = _child_dir(local_fd, "state", uid, private=True)
                finally:
                    os.close(local_fd)
            finally:
                os.close(home_fd)
            _no_uncertain(self._state_fd)
            self._lock_fd = os.open(LOCK_NAME, _FILE_FLAGS, 0o600, dir_fd=self._state_fd)
            info = os.fstat(self._lock_fd)
            if info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o600:
                raise Invalid()
            _same_inode(self._lock_fd, self._state_fd)
            until = min(self.started + self.wait_seconds, self.started + TOTAL_SECONDS)
            while True:
                try:
                    fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except InterruptedError:
                    continue
                except BlockingIOError:
                    remaining = until - time.monotonic()
                    if remaining <= 0:
                        raise Busy()
                    time.sleep(min(0.05, remaining))
            _same_inode(self._lock_fd, self._state_fd)
            _no_uncertain(self._state_fd)
            if self.remaining <= 0:
                raise TimedOut()
            return self
        except OSError:
            self.close()
            raise Invalid() from None
        except BaseException:
            self.close()
            raise

    @property
    def remaining(self) -> float:
        if self.started is None:
            raise Invalid()
        return max(0.0, TOTAL_SECONDS - (time.monotonic() - self.started))

    def fileno(self) -> int:
        if self._lock_fd is None:
            raise Invalid()
        return self._lock_fd

    def mark_uncertain(self, reason: str) -> None:
        """Persist a fail-closed incident while holding the lock.

        Only an independently authorized operator may clear the incident.
        The marker is deliberately *not* an expiring lock or retry journal.
        """
        if self._lock_fd is None or self._state_fd is None:
            raise Invalid()
        if reason not in ("process_unverified", "remote_unverified", "cleanup_failed", "supervisor_interrupted"):
            raise Invalid()
        _same_inode(self._lock_fd, self._state_fd)
        marker = json.dumps({"schema": 1, "reason": reason}, sort_keys=True).encode() + b"\n"
        try:
            fd = os.open(UNCERTAIN_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self._state_fd)
        except FileExistsError:
            raise Uncertain() from None
        try:
            os.write(fd, marker)
            os.fsync(fd)
            os.fsync(self._state_fd)
        finally:
            os.close(fd)

    def close(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        if self._state_fd is not None:
            os.close(self._state_fd)
            self._state_fd = None

    def __exit__(self, *_: object) -> None:
        self.close()
