"""Fail-forward enrollment provisioning and WireGuard runtime adapter.

This module owns ordered locking, durable backup and replay. Never reset an
unknown live peer or overwrite unrelated operator-managed configuration.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from ipaddress import ip_network
from pathlib import Path
from typing import Callable

from .watchtower_enrollment_ledger import Enrollment, EnrollmentFailure, Ledger

MANAGED_BEGIN = "# BEGIN gway-remote enrollment: "
MANAGED_END = "# END gway-remote enrollment: "


def occupied_addresses(config: str) -> set[str]:
    """Read every existing AllowedIPs value, never rewrite unmanaged blocks."""
    values: set[str] = set()
    section = ""
    for raw in config.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line
        elif section == "[Peer]" and line.startswith("AllowedIPs") and "=" in line:
            values.update(item.strip() for item in line.split("=", 1)[1].split(",") if item.strip())
    return values


def render_managed_peer(config: str, enrollment: Enrollment) -> str:
    """Append exactly one owned block; the pre-existing config bytes are retained."""
    marker = MANAGED_BEGIN + enrollment.device
    if marker in config:
        return config
    suffix = "" if not config or config.endswith("\n") else "\n"
    return config + suffix + f"{marker}\n[Peer]\n# Device = {enrollment.device}\nPublicKey = {enrollment.public_key}\nAllowedIPs = {enrollment.address}\n{MANAGED_END}{enrollment.device}\n"


class WireGuard:
    def set_peer(self, public_key: str, address: str) -> None:
        raise NotImplementedError

    def has_peer(self, public_key: str, address: str) -> bool:
        raise NotImplementedError

    def remove_peer(self, public_key: str) -> None:
        raise NotImplementedError


class SubprocessWireGuard(WireGuard):
    def __init__(self, interface: str = "gway", runner: Callable = subprocess.run):
        self.interface, self.runner = interface, runner

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return self.runner(["wg", *args], check=True, text=True, capture_output=True)

    def set_peer(self, public_key: str, address: str) -> None:
        self._run("set", self.interface, "peer", public_key, "allowed-ips", address)

    def has_peer(self, public_key: str, address: str) -> bool:
        result = self._run("show", self.interface, "allowed-ips")
        return any(
            line.startswith(public_key + "\t") and address in {part.strip() for part in line.split("\t", 1)[1].split(",")}
            for line in result.stdout.splitlines()
        )

    def remove_peer(self, public_key: str) -> None:
        self._run("set", self.interface, "peer", public_key, "remove")


class Provisioner:
    """Ordered file/runtime operation with recorded rollback material."""
    def __init__(self, ledger: Ledger, config: Path, backups: Path, wireguard: WireGuard):
        self.ledger, self.config, self.backups, self.wireguard = ledger, Path(config), Path(backups), wireguard
        self._thread_lock = threading.RLock()

    def _write(self, desired: str) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".gway-remote-", dir=self.config.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(desired)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.config)
            if self.config.read_text(encoding="utf-8") != desired:
                raise EnrollmentFailure("Watchtower config verification failed")
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _prepare_backup(self, operation: dict, current: str) -> str:
        """Write a durable original once; retries must never overwrite it."""
        backup = Path(operation["backup_path"])
        self.backups.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return backup.read_text(encoding="utf-8")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(current)
            handle.flush()
            os.fsync(handle.fileno())
        return current

    def _resume(self, operation: dict) -> None:
        if operation["state"] == "failed":
            raise EnrollmentFailure("Watchtower enrollment needs operator review")
        enrollment = Enrollment(operation["id"], operation["device"],
                                operation["public_key"], operation["address"])
        current = self.config.read_text(encoding="utf-8")
        original = self._prepare_backup(operation, current)
        expected = render_managed_peer(original, enrollment)
        # Never restore old snapshots or remove an existing peer. Unrelated
        # changes are ambiguous: block enrollment for operator inspection.
        if current not in (original, expected):
            self.ledger.advance(enrollment.operation_id, "failed",
                                detail="configuration differs from recorded operation")
            raise EnrollmentFailure("Watchtower configuration requires operator review")
        if current == original:
            if MANAGED_BEGIN + enrollment.device in original:
                raise EnrollmentFailure("existing managed peer needs operator review")
            self._write(expected)
        self.ledger.advance(enrollment.operation_id, "config_written",
                            backup_path=str(self.backups / f"{enrollment.operation_id}.conf"))
        if not self.wireguard.has_peer(enrollment.public_key, enrollment.address):
            self.wireguard.set_peer(enrollment.public_key, enrollment.address)
        if not self.wireguard.has_peer(enrollment.public_key, enrollment.address):
            raise EnrollmentFailure("Watchtower runtime peer verification failed")
        self.ledger.advance(enrollment.operation_id, "runtime_applied")
        self.ledger.advance(enrollment.operation_id, "committed")

    @contextmanager
    def _config_lock(self):
        """Serialize allocation through the matching config/runtime mutation."""
        import fcntl

        lock_path = self.config.with_name(self.config.name + ".gway-remote.lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def enroll(self, device: str, public_key: str, token: str, *, ssh_host_key: str | None = None) -> Enrollment:
        with self._thread_lock, self._config_lock():
            # Finish any previous operation before allocating another address.
            self._recover_locked()
            original = self.config.read_text(encoding="utf-8")
            enrollment = self.ledger.reserve(device=device, public_key=public_key, token=token,
                                             occupied=occupied_addresses(original), backup_directory=self.backups, ssh_host_key=ssh_host_key)
            if not enrollment.already_active:
                operation = next(item for item in self.ledger.pending()
                                 if item["id"] == enrollment.operation_id)
                self._resume(operation)
            return enrollment

    def repair_host_identity(self, device: str, public_key: str, token: str,
                             *, ssh_host_key: str) -> Enrollment:
        return self.ledger.repair_host_identity(
            device=device, public_key=public_key, token=token,
            ssh_host_key=ssh_host_key,
        )

    def _recover_locked(self) -> int:
        recovered = 0
        for operation in self.ledger.pending():
            self._resume(operation)
            recovered += 1
        return recovered

    def recover(self) -> int:
        with self._thread_lock, self._config_lock():
            return self._recover_locked()


