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

from .wireguard_enrollment_contract import DEVICE, InvalidEnrollment, MAX_REQUEST_BYTES, parse_enrollment_json

MANAGED_BEGIN = "# BEGIN gway-remote enrollment: "
MANAGED_END = "# END gway-remote enrollment: "


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class EnrollmentRejected(Exception):
    """Public-safe rejection.  Messages must not interpolate request fields."""


class EnrollmentFailure(Exception):
    """Operator-visible local failure; never returned to the HTTP client."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY,
    device TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    revoked_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_invitation
    ON invitations(device) WHERE consumed_at IS NULL AND revoked_at IS NULL;
CREATE TABLE IF NOT EXISTS bootstrap_sessions (
    id TEXT PRIMARY KEY,
    session_hash TEXT NOT NULL UNIQUE,
    invitation_id TEXT NOT NULL REFERENCES invitations(id),
    device TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS devices (
    device TEXT PRIMARY KEY,
    public_key TEXT NOT NULL UNIQUE,
    address TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK(state IN ('pending','active','revoked')),
    operation_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY,
    device TEXT NOT NULL,
    public_key TEXT NOT NULL,
    address TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('reserved','config_written','runtime_applied','committed','rolled_back','failed')),
    backup_path TEXT,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Enrollment:
    operation_id: str
    device: str
    public_key: str
    address: str
    already_active: bool = False


class Ledger:
    """Durable registry. Tokens are hashes; request tokens are never persisted."""

    def __init__(self, path: Path, *, network: str, gateway: str):
        self.path = Path(path)
        self.network = ip_network(network, strict=True)
        if not isinstance(self.network, IPv4Network):
            raise ValueError("Watchtower network must be IPv4")
        self.gateway = IPv4Address(gateway)
        if self.gateway not in self.network:
            raise ValueError("gateway must be inside Watchtower network")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("unsafe enrollment ledger")
        with self._connect() as connection:
            connection.executescript(SCHEMA)
        self.path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _transaction(self):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    def invite(self, device: str, *, minutes: int = 15) -> dict:
        if not isinstance(device, str) or not DEVICE.fullmatch(device):
            raise ValueError("invalid Watchtower device")
        if not 1 <= minutes <= 60:
            raise ValueError("invitation lifetime must be between 1 and 60 minutes")
        token = secrets.token_urlsafe(32)
        ident = secrets.token_hex(16)
        expires = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        with self._transaction() as connection:
            connection.execute("UPDATE invitations SET revoked_at=? WHERE device=? AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at<=?", (_now(), device, _now()))
            connection.execute("INSERT INTO invitations(id,device,token_hash,expires_at) VALUES(?,?,?,?)", (ident, device, _digest(token), expires))
        return {"id": ident, "device": device, "token": token, "expires_at": expires}

    def register(self, device: str, *, minutes: int = 15, public_url: str) -> dict:
        """Create one short-lived URL bearer; underlying invitation token stays private."""
        from urllib.parse import urlsplit

        origin = urlsplit(public_url)
        if (origin.scheme != "https" or origin.hostname != "register.gelectriic.com"
                or origin.username or origin.password or origin.query or origin.fragment
                or origin.path not in ("", "/") or origin.port not in (None, 443)):
            raise ValueError("invalid approved registration origin")
        invitation = self.invite(device, minutes=minutes)
        secret = secrets.token_urlsafe(32)
        session_id = secrets.token_hex(16)
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO bootstrap_sessions(id,session_hash,invitation_id,device,expires_at) VALUES(?,?,?,?,?)",
                (session_id, _digest(secret), invitation["id"], device, invitation["expires_at"]),
            )
        return {"id": session_id, "device": device,
                "url": f"https://register.gelectriic.com/v1/bootstrap/{secret}",
                "expires_at": invitation["expires_at"]}

    def bootstrap_session(self, secret: str) -> dict:
        """Inspect a URL bearer without exposing an invitation or changing state."""
        if not isinstance(secret, str) or len(secret) > 128 or len(secret) < 32:
            raise EnrollmentRejected("bootstrap rejected")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT s.*, i.revoked_at AS invitation_revoked, i.consumed_at AS invitation_consumed "
                "FROM bootstrap_sessions s JOIN invitations i ON i.id=s.invitation_id "
                "WHERE s.session_hash=?", (_digest(secret),),
            ).fetchone()
        if (row is None or row["revoked_at"] or row["consumed_at"] or
                row["invitation_revoked"] or
                row["expires_at"] <= _now()):
            raise EnrollmentRejected("bootstrap rejected")
        return {"id": row["id"], "device": row["device"], "expires_at": row["expires_at"]}

    def complete_bootstrap(self, secret: str, device: str, public_key: str) -> bool:
        """Consume URL after client confirms local installation and startup."""
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM bootstrap_sessions WHERE session_hash=?", (_digest(secret),),
            ).fetchone()
            if row is None or row["device"] != device or row["revoked_at"]:
                raise EnrollmentRejected("bootstrap rejected")
            peer = connection.execute(
                "SELECT 1 FROM devices WHERE device=? AND public_key=? AND state='active'",
                (device, public_key),
            ).fetchone()
            if peer is None:
                raise EnrollmentRejected("bootstrap rejected")
            if row["consumed_at"]:
                return False
            connection.execute(
                "UPDATE bootstrap_sessions SET consumed_at=? WHERE id=?", (_now(), row["id"]),
            )
            return True

    def revoke_bootstrap(self, session_id: str) -> bool:
        """Revoke bootstrap and matching unused invitation together."""
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT invitation_id FROM bootstrap_sessions WHERE id=? AND revoked_at IS NULL "
                "AND consumed_at IS NULL", (session_id,),
            ).fetchone()
            if row is None:
                return False
            now = _now()
            connection.execute("UPDATE bootstrap_sessions SET revoked_at=? WHERE id=?", (now, session_id))
            connection.execute("UPDATE invitations SET revoked_at=? WHERE id=? AND consumed_at IS NULL",
                               (now, row["invitation_id"]))
        return True

    def bootstrap_status(self) -> list[dict]:
        """Metadata only: no invitation tokens, bearer values, or their hashes."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,device,expires_at,consumed_at,revoked_at FROM bootstrap_sessions "
                "ORDER BY expires_at DESC LIMIT 100"
            )
            return [dict(row) for row in rows]

    def revoke(self, invitation_id: str) -> bool:
        with self._transaction() as connection:
            result = connection.execute("UPDATE invitations SET revoked_at=? WHERE id=? AND consumed_at IS NULL AND revoked_at IS NULL", (_now(), invitation_id))
        return result.rowcount == 1

    def _allocate(self, connection: sqlite3.Connection, occupied: Iterable[str]) -> str:
        reserved = {self.gateway}
        for value in occupied:
            try:
                item = ip_network(value, strict=False)
            except ValueError:
                continue
            if item.version == 4:
                reserved.update(item.hosts() if item.prefixlen < 32 else [item.network_address])
        reserved.update(IPv4Address(row[0].split("/", 1)[0]) for row in connection.execute("SELECT address FROM devices WHERE state != 'revoked'"))
        for candidate in self.network.hosts():
            if candidate not in reserved:
                return f"{candidate}/32"
        raise EnrollmentFailure("Watchtower address pool is exhausted")

    def reserve(self, *, device: str, public_key: str, token: str, occupied: Iterable[str], backup_directory: Path | None = None) -> Enrollment:
        now = _now()
        token_hash = _digest(token)
        with self._transaction() as connection:
            invitation = connection.execute("SELECT * FROM invitations WHERE token_hash=?", (token_hash,)).fetchone()
            if invitation is None:
                session = connection.execute(
                    "SELECT * FROM bootstrap_sessions WHERE session_hash=?", (token_hash,),
                ).fetchone()
                if (session is None or session["device"] != device or session["revoked_at"]
                        or session["consumed_at"] or session["expires_at"] <= now):
                    raise EnrollmentRejected("enrollment rejected")
                invitation = connection.execute(
                    "SELECT * FROM invitations WHERE id=?", (session["invitation_id"],),
                ).fetchone()
                token_hash = invitation["token_hash"]
            if invitation is None or invitation["revoked_at"]:
                raise EnrollmentRejected("enrollment rejected")
            if invitation["device"] != device:
                raise EnrollmentRejected("enrollment rejected")
            existing = connection.execute("SELECT * FROM devices WHERE device=?", (device,)).fetchone()
            if existing is not None:
                if existing["public_key"] != public_key or existing["state"] == "revoked":
                    raise EnrollmentRejected("enrollment rejected")
                operation = connection.execute("SELECT * FROM operations WHERE id=?", (existing["operation_id"],)).fetchone()
                if operation and operation["state"] == "committed":
                    return Enrollment(operation["id"], device, public_key, existing["address"], True)
                return Enrollment(existing["operation_id"], device, public_key, existing["address"])
            if invitation["consumed_at"] or invitation["expires_at"] <= now:
                raise EnrollmentRejected("enrollment rejected")
            duplicate = connection.execute("SELECT 1 FROM devices WHERE public_key=?", (public_key,)).fetchone()
            if duplicate:
                raise EnrollmentRejected("enrollment rejected")
            address = self._allocate(connection, occupied)
            operation_id = secrets.token_hex(16)
            backup_path = str(Path(backup_directory) / f"{operation_id}.conf") if backup_directory else None
            connection.execute("INSERT INTO devices(device,public_key,address,state,operation_id) VALUES(?,?,?,?,?)", (device, public_key, address, "pending", operation_id))
            connection.execute("INSERT INTO operations(id,device,public_key,address,token_hash,state,backup_path,created_at,updated_at) VALUES(?,?,?,?,?,'reserved',?,?,?)", (operation_id, device, public_key, address, token_hash, backup_path, now, now))
        return Enrollment(operation_id, device, public_key, address)

    def advance(self, operation_id: str, state: str, *, backup_path: str | None = None, detail: str = "") -> None:
        allowed = {"config_written", "runtime_applied", "committed", "rolled_back", "failed"}
        if state not in allowed:
            raise ValueError("invalid operation state")
        with self._transaction() as connection:
            result = connection.execute("UPDATE operations SET state=?, backup_path=COALESCE(?, backup_path), detail=?, updated_at=? WHERE id=?", (state, backup_path, detail, _now(), operation_id))
            if result.rowcount != 1:
                raise EnrollmentFailure("unknown Watchtower operation")
            if state == "committed":
                operation = connection.execute("SELECT token_hash FROM operations WHERE id=?", (operation_id,)).fetchone()
                connection.execute("UPDATE devices SET state='active' WHERE operation_id=?", (operation_id,))
                connection.execute("UPDATE invitations SET consumed_at=? WHERE token_hash=?", (_now(), operation["token_hash"]))
            elif state in {"rolled_back", "failed"}:
                connection.execute("DELETE FROM devices WHERE operation_id=? AND state='pending'", (operation_id,))

    def pending(self) -> list[dict]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM operations WHERE state NOT IN ('committed','rolled_back') ORDER BY created_at")]

    def status(self) -> dict:
        with self._connect() as connection:
            return {"invitations": connection.execute("SELECT count(*) FROM invitations WHERE consumed_at IS NULL AND revoked_at IS NULL").fetchone()[0], "devices": connection.execute("SELECT count(*) FROM devices WHERE state='active'").fetchone()[0], "pending_operations": connection.execute("SELECT count(*) FROM operations WHERE state NOT IN ('committed','rolled_back')").fetchone()[0]}


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

    def enroll(self, device: str, public_key: str, token: str) -> Enrollment:
        with self._thread_lock, self._config_lock():
            # Finish any previous operation before allocating another address.
            self._recover_locked()
            original = self.config.read_text(encoding="utf-8")
            enrollment = self.ledger.reserve(device=device, public_key=public_key, token=token,
                                             occupied=occupied_addresses(original), backup_directory=self.backups)
            if not enrollment.already_active:
                operation = next(item for item in self.ledger.pending()
                                 if item["id"] == enrollment.operation_id)
                self._resume(operation)
            return enrollment

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

        def _script(self, secret: str, device: str, server_key: str) -> bytes:
            """HTTPS-distributed stage-one script; never includes an invitation token."""
            # URL bearer characters are restricted by the route regexp.
            source = f"""#!/bin/sh
set -eu
umask 077
if [ "$(id -u)" != 0 ]; then echo 'bootstrap requires root' >&2; exit 1; fi
command -v apt-get >/dev/null || {{ echo 'unsupported distribution' >&2; exit 1; }}
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 curl wireguard-tools
temp="$(mktemp -d)"
trap 'rm -rf "$temp"' EXIT HUP INT TERM
curl -fsS --proto '=https' --max-redirs 0 'https://register.gelectriic.com/v1/bootstrap/{secret}/client.py' -o "$temp/client.py"
printf '%s' '{secret}' > "$temp/session"
python3 "$temp/client.py" bootstrap --device '{device}' --server-public-key '{server_key}' --token-file "$temp/session"
pub="$(wg show gway public-key)"
printf '{{"device":"%s","public_key":"%s"}}' '{device}' "$pub" > "$temp/ack.json"
curl -fsS --proto '=https' --max-redirs 0 -X POST -H 'Content-Type: application/json' --data-binary @"$temp/ack.json" 'https://register.gelectriic.com/v1/bootstrap/{secret}/complete' >/dev/null
"""
            return source.encode("utf-8")

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
            bootstrap_match = re.fullmatch(
                r"/v1/bootstrap/([A-Za-z0-9_-]{32,128})(/client\\.py)?", self.path,
            )
            if bootstrap_match and not read_only_stage and provisioner is not None:
                try:
                    session = provisioner.ledger.bootstrap_session(bootstrap_match.group(1))
                    if bootstrap_match.group(2):
                        data = Path(__file__).with_name("wireguard_satellite.py").read_bytes()
                        self._send_artifact(data, "text/x-python; charset=utf-8")
                    else:
                        key = subprocess.run(
                            ["wg", "show", "gway", "public-key"], check=True,
                            capture_output=True, text=True,
                        ).stdout.strip()
                        self._send_artifact(
                            self._script(bootstrap_match.group(1), session["device"], key),
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
                    provisioner.ledger.complete_bootstrap(
                        completion.group(1), data["device"], data["public_key"],
                    )
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
                device, public_key, token = parse_enrollment_json(self.rfile.read(length))
                if read_only_stage:
                    raise EnrollmentRejected("enrollment rejected")
                if provisioner is None:
                    raise RuntimeError("Watchtower provisioner is unavailable")
                enrollment = provisioner.enroll(device, public_key, token)
            except (InvalidEnrollment, ValueError):
                self._send(400, {"error": "invalid_request"})
            except EnrollmentRejected:
                self._send(403, {"error": "enrollment_rejected"})
            except Exception:
                self._send(500, {"error": "enrollment_failed"})
            else:
                self._send(200, {"device": enrollment.device, "address": enrollment.address, "public_key": enrollment.public_key, "server_endpoint": wireguard_endpoint, "server_public_key": subprocess.run(["wg", "show", "gway", "public-key"], check=True, capture_output=True, text=True).stdout.strip(), "server_tunnel_ip": str(provisioner.ledger.gateway), "enrollment_url": public_url, "created": not enrollment.already_active})
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
