"""Opt-in bounded process/cgroup supervision for a held maintenance flock.

Not connected to installers. A *dedicated pre-provisioned cgroup v2* is
mandatory: without provable membership/quiescence this API fails closed.
It does not create systemd services, alter node configuration, or provide
remote-effect attestation. See docs/maintenance-lock-v1.md.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Callable, Sequence

from .maintenance_lock import Invalid, MaintenanceLock, TOTAL_SECONDS, Uncertain

TERM_AT_SECONDS = 275
KILL_AT_SECONDS = 290
POLL_SECONDS = 0.1


@dataclass(frozen=True)
class ProcessOutcome:
    """A completed subprocess is NOT independently verified release health."""
    state: str
    exit_code: int | None
    elapsed: float

    @property
    def suggested_exit_code(self) -> int:
        if self.state == "TIMEOUT":
            return 124
        return 0 if self.exit_code == 0 else 1


class CgroupV2:
    """A dedicated, already-provisioned cgroup v2 scope.

    The path must come from a trusted local systemd/delegation adapter, not
    from an MCP caller. Systemd unit ownership/isolation must be checked by
    that adapter before real deployment integration.
    """

    def __init__(self, path: str | Path, *, root: str | Path = "/sys/fs/cgroup"):
        self.root = Path(root)
        self.path = Path(path)
        if not self.root.is_absolute() or not self.path.is_absolute():
            raise Invalid()
        try:
            parts = self.path.relative_to(self.root).parts
        except ValueError:
            raise Invalid() from None
        if not parts or any(part in (".", "..") for part in parts):
            raise Invalid()
        for ancestor in (self.root, *list(reversed(self.path.parents))[-len(parts):], self.path):
            if ancestor.is_symlink():
                raise Invalid()
        self.relative = "/" + "/".join(parts)

    def _read(self, name: str) -> str:
        fd = os.open(self.path / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            with os.fdopen(fd, "r") as stream:
                return stream.read(65536)
        except BaseException:
            raise

    def empty(self) -> bool:
        fields = dict(line.split(None, 1) for line in self._read("cgroup.events").splitlines() if line.strip())
        if fields.get("populated") not in ("0", "1"):
            raise Invalid()
        return fields["populated"] == "0"

    def attach(self, pid: int) -> None:
        if type(pid) is not int or pid <= 1:
            raise Invalid()
        fd = os.open(self.path / "cgroup.procs", os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.write(fd, str(pid).encode("ascii"))
        finally:
            os.close(fd)

    def contains(self, pid: int) -> bool:
        text = Path(f"/proc/{pid}/cgroup").read_text(encoding="ascii")
        return any(line == "0::" + self.relative or
                   line.startswith("0::" + self.relative + "/")
                   for line in text.splitlines())

    def term(self, leader_pid: int) -> None:
        # Cooperative TERM to leader's process group; detached sessions in
        # the dedicated cgroup are covered by the later cgroup.kill.
        try:
            os.killpg(leader_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def kill(self) -> None:
        # Linux cgroup v2: recursively SIGKILL all descendants, including
        # detached sessions. Missing controller -> fail closed, not pid-only.
        fd = os.open(self.path / "cgroup.kill", os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.write(fd, b"1")
        finally:
            os.close(fd)


def _child_gate(argv: Sequence[str]) -> None:
    """Private subprocess entrypoint: wait for parent cgroup attestation."""
    if len(argv) < 2 or not argv[0].isdecimal() or not argv[1:]:
        os._exit(126)
    fd = int(argv[0])
    try:
        authorized = os.read(fd, 1) == b"G"
        os.close(fd)
        if not authorized:
            os._exit(126)
        os.execvp(argv[1], list(argv[1:]))
    except (OSError, ValueError):
        os._exit(126)


def _record_uncertain(lock: MaintenanceLock, reason: str) -> None:
    try:
        lock.mark_uncertain(reason)
    except Uncertain:
        pass  # Existing fail-closed marker remains authoritative.
    # If persistence fails otherwise, propagate the error: never certify
    # TIMEOUT/SUCCESS in the absence of the safety marker.


def run_supervised(
    argv: Sequence[str],
    *,
    lock: MaintenanceLock,
    scope: CgroupV2,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
    spawn: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> ProcessOutcome:
    """Run trusted argv under one already held lock and dedicated cgroup.

    Includes lock acquisition time in deadline. The child blocks on a pipe
    until added to the cgroup and membership is attested; any failed attach
    closes the gate without allowing installation effects. No shell.

    A returned process exit code is NOT deployment verification; callers
    must perform their health checks inside the same lock and deadline.
    """
    if (not argv or not isinstance(argv, (tuple, list)) or
            any(type(arg) is not str or not arg or "\x00" in arg for arg in argv)):
        raise Invalid()
    if not isinstance(lock, MaintenanceLock) or lock.started is None:
        raise Invalid()
    lock_fd = lock.fileno()
    if clock() >= lock.started + TOTAL_SECONDS:
        raise Uncertain()
    if not scope.empty():
        raise Uncertain()
    rd = wr = None
    process = None
    released = False
    incident = False
    terminal = False
    try:
        rd, wr = os.pipe2(os.O_CLOEXEC)
        process = spawn(
            [sys.executable, "-m", "gway_remote.maintenance_supervisor",
             "--gate", str(rd), *argv],
            start_new_session=True, pass_fds=(rd, lock_fd),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
        )
        os.close(rd)
        rd = None
        scope.attach(process.pid)
        if not scope.contains(process.pid):
            raise Invalid()
        if clock() >= lock.started + TOTAL_SECONDS:
            raise Invalid()
        os.write(wr, b"G")
        os.close(wr)
        wr = None
        released = True

        term_sent = False
        kill_sent = False
        deadline = lock.started + TOTAL_SECONDS
        while True:
            now = clock()
            result = process.poll()
            if result is not None and scope.empty():
                terminal = True
                return ProcessOutcome(
                    "TIMEOUT" if term_sent or kill_sent or now >= deadline else "EXITED",
                    result,
                    max(0.0, now - lock.started),
                )
            if now >= deadline:
                _record_uncertain(lock, "process_unverified")
                incident = True
                raise Uncertain()
            if not term_sent and now >= lock.started + TERM_AT_SECONDS:
                scope.term(process.pid)
                term_sent = True
            if not kill_sent and now >= lock.started + KILL_AT_SECONDS:
                scope.kill()
                kill_sent = True
            pause(min(POLL_SECONDS, max(0.0, deadline - now)))
    except BaseException:
        if process is not None and not terminal:
            # Closing the gate on pre-exec failures prevents starting argv.
            if released and not incident:
                try:
                    scope.kill()
                except (OSError, RuntimeError, ValueError):
                    pass
                _record_uncertain(lock, "supervisor_interrupted")
                # A failed controller probe/kill is not an ordinary FAILED
                # installation. Its effects cannot be proven quiescent.
                raise Uncertain() from None
            elif not released:
                # The blocked child has not executed the installer. Still
                # verify/terminate it when possible; no false success.
                try:
                    scope.kill()
                except (OSError, RuntimeError, ValueError):
                    pass
        raise
    finally:
        for fd in (rd, wr):
            if fd is not None:
                os.close(fd)
        # Caller owns the lock and its lifetime; never release it here.


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] != "--gate":
        raise SystemExit(126)
    _child_gate(sys.argv[2:])
