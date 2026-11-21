"""GWAY Remote-owned Watchtower enrollment service.

This module deliberately has no deployment side effects.  It is designed for a
root-owned, loopback-only systemd unit; its public surface is limited to the
health endpoint and the single enrollment POST route.
"""
from __future__ import annotations

import hashlib
import json
import re
import os
import secrets
import sqlite3
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address, IPv4Network, ip_network
from pathlib import Path
from typing import Callable, Iterable

from .bootstrap_script import render_bootstrap_script
from .watchtower_enrollment_ledger import (
    SCHEMA, Enrollment, EnrollmentRejected, EnrollmentFailure, Ledger, _now, _digest,
)
from .wireguard_enrollment_contract import DEVICE, InvalidEnrollment, MAX_REQUEST_BYTES, parse_enrollment_json, parse_host_identity_enrollment, validate_enrollment

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


def make_handler(provisioner: Provisioner | None, *, public_url: str, wireguard_endpoint: str,
                 read_only_stage: bool = False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "gway-remote-watchtower"
        sys_version = ""

        def log_message(self, *_args) -> None:
            return

        def _send(self, status: int, payload: dict) -> None:
            encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(encoded)

        def _script(self, secret: str, device: str, server_key: str,
                    *, repair_host_identity: bool = False) -> bytes:
            """HTTPS-distributed stage-one script; never includes an invitation token."""
            # URL bearer characters are restricted by the route regexp.
            return render_bootstrap_script(secret, device, server_key,
                                           repair_host_identity=repair_host_identity)

        def _send_artifact(self, data: bytes, media_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", media_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_GET(self) -> None:
            from urllib.parse import urlsplit
            parsed_path = urlsplit(self.path)
            bootstrap_match = re.fullmatch(
                r"/v1/bootstrap/([A-Za-z0-9_-]{32,128})(/client\.py)?", parsed_path.path,
            )
            if bootstrap_match and not read_only_stage and provisioner is not None:
                try:
                    session = provisioner.ledger.bootstrap_session(bootstrap_match.group(1))
                    expected_query = "replace=true" if session["replace"] and not bootstrap_match.group(2) else ""
                    if parsed_path.query != expected_query or parsed_path.fragment:
                        raise EnrollmentRejected("bootstrap rejected")
                    if session["replace"]:
                        # No replacement transaction is implemented yet: never present a regular
                        # enrollment script as a valid replacement operation.
                        raise EnrollmentRejected("replacement bootstrap not yet supported")
                    if bootstrap_match.group(2):
                        data = Path(__file__).with_name("wireguard_satellite.py").read_bytes()
                        self._send_artifact(data, "text/x-python; charset=utf-8")
                    else:
                        key = subprocess.run(
                            ["wg", "show", "gway", "public-key"], check=True,
                            capture_output=True, text=True,
                        ).stdout.strip()
                        self._send_artifact(
                            self._script(bootstrap_match.group(1), session["device"], key,
                                         repair_host_identity=session["repair_host_identity"]),
                            "text/x-shellscript; charset=utf-8",
                        )
                except (EnrollmentRejected, OSError, subprocess.CalledProcessError):
                    self._send(404, {"error": "not_found"})
                return
            if self.path == "/health":
                self._send(200, {"ok": True, "service": "gway-remote-watchtower", "enrollment_url": public_url})
            else:
                self._send(404, {"error": "not_found"})

        do_HEAD = do_GET

        def do_POST(self) -> None:
            completion = re.fullmatch(
                r"/v1/bootstrap/([A-Za-z0-9_-]{32,128})/complete", self.path,
            )
            if completion and not read_only_stage and provisioner is not None:
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 1024:
                        raise ValueError("bad request")
                    data = json.loads(self.rfile.read(size))
                    if not isinstance(data, dict) or set(data) != {"device", "public_key"}:
                        raise ValueError("bad request")
                    device, public_key, _session = validate_enrollment(
                        {"device": data["device"], "public_key": data["public_key"],
                         "token": completion.group(1)}
                    )
                    provisioner.ledger.complete_bootstrap(completion.group(1), device, public_key)
                except (ValueError, TypeError, KeyError):
                    self._send(400, {"error": "invalid_request"})
                except EnrollmentRejected:
                    self._send(403, {"error": "enrollment_rejected"})
                else:
                    self._send(200, {"complete": True})
                return
            if self.path != "/v1/enroll":
                self._send(404, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_REQUEST_BYTES:
                    raise InvalidEnrollment("invalid enrollment request")
                device, public_key, token, ssh_host_key, repair_host_identity = parse_host_identity_enrollment(self.rfile.read(length))
                if read_only_stage:
                    raise EnrollmentRejected("enrollment rejected")
                if provisioner is None:
                    raise RuntimeError("Watchtower provisioner is unavailable")
                if repair_host_identity:
                    enrollment = provisioner.repair_host_identity(
                        device, public_key, token, ssh_host_key=ssh_host_key,
                    )
                else:
                    enrollment = (provisioner.enroll(device, public_key, token, ssh_host_key=ssh_host_key)
                                  if ssh_host_key is not None else provisioner.enroll(device, public_key, token))
            except (InvalidEnrollment, ValueError):
                self._send(400, {"error": "invalid_request"})
            except EnrollmentRejected:
                self._send(403, {"error": "enrollment_rejected"})
            except Exception:
                self._send(500, {"error": "enrollment_failed"})
            else:
                self._send(200, {"device": enrollment.device, "address": enrollment.address, "public_key": enrollment.public_key, "server_endpoint": wireguard_endpoint, "server_public_key": subprocess.run(["wg", "show", "gway", "public-key"], check=True, capture_output=True, text=True).stdout.strip(), "server_tunnel_ip": str(provisioner.ledger.gateway), "enrollment_url": public_url, "created": not enrollment.already_active, "repaired": repair_host_identity})
    return Handler


def serve(provisioner: Provisioner | None, *, host: str, port: int, public_url: str,
          wireguard_endpoint: str, read_only_stage: bool = False) -> None:
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("Watchtower service must bind a loopback address")
    if read_only_stage:
        if provisioner is not None:
            raise ValueError("read-only stage must not receive a provisioner")
    elif provisioner is None:
        raise ValueError("active Watchtower service requires a provisioner")
    else:
        provisioner.recover()
    httpd = ThreadingHTTPServer((host, port), make_handler(
        provisioner, public_url=public_url, wireguard_endpoint=wireguard_endpoint,
        read_only_stage=read_only_stage))
    httpd.serve_forever()
