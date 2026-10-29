"""Recoverable Watchtower half of the gway-replace-v1 protocol.

All entry points run under the enrollment provisioner's process/file locks.
The current device stays active until a fresh-handshake acknowledgment is
durable. Rekeys use a distinct /32, so WireGuard never transfers AllowedIPs
away from a working peer while the satellite is preparing its configuration.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import time
from ipaddress import ip_network
from pathlib import Path

from .watchtower_enrollment import (
    Enrollment, EnrollmentFailure, EnrollmentRejected, MANAGED_BEGIN,
    MANAGED_END, _digest, _now, render_managed_peer,
)
from .wireguard_enrollment_contract import TOKEN, validate_enrollment

PROTOCOL = "gway-replace-v1"
TERMINAL = {"committed", "rolled_back"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS replacements (
    id TEXT PRIMARY KEY,
    device TEXT NOT NULL,
    session_hash TEXT NOT NULL UNIQUE,
    invitation_id TEXT NOT NULL UNIQUE,
    public_key TEXT NOT NULL,
    address TEXT NOT NULL,
    old_device TEXT NOT NULL,
    old_identity TEXT,
    state TEXT NOT NULL CHECK(state IN
        ('reserved','prepared','acknowledged','rolling_back','committed','rolled_back')),
    backup_path TEXT NOT NULL,
    config_digest TEXT NOT NULL,
    handshake_after INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_replacement
    ON replacements(device) WHERE state NOT IN ('committed','rolled_back');
"""


def _peers(config: str) -> dict[str, tuple[str, ...]]:
    """Parse ownership-relevant fields without rewriting any configuration."""
    result = {}
    current = None

    def finish():
        if current is None:
            return
        if set(current) != {"PublicKey", "AllowedIPs"} or current["PublicKey"] in result:
            raise EnrollmentFailure("ambiguous Watchtower peer configuration")
        try:
            addresses = tuple(sorted(str(ip_network(v.strip(), strict=True))
                                     for v in current["AllowedIPs"].split(",")))
        except ValueError:
            raise EnrollmentFailure("invalid Watchtower peer configuration") from None
        result[current["PublicKey"]] = addresses

    for raw in config.splitlines():
        line = raw.strip()
        if line.startswith("["):
            finish()
            current = {} if line == "[Peer]" else None
        elif current is not None and "=" in line and not line.startswith(("#", ";")):
            name, value = (v.strip() for v in line.split("=", 1))
            if name in {"PublicKey", "AllowedIPs"}:
                if name in current:
                    raise EnrollmentFailure("ambiguous Watchtower peer configuration")
                current[name] = value
    finish()
    return result


def _block(config: str, begin: str, end: str) -> str | None:
    lines = config.splitlines(keepends=True)
    starts = [n for n, line in enumerate(lines) if line.rstrip("\n") == begin]
    stops = [n for n, line in enumerate(lines) if line.rstrip("\n") == end]
    if not starts and not stops:
        return None
    if len(starts) != 1 or len(stops) != 1 or starts[0] >= stops[0]:
        raise EnrollmentFailure("ambiguous Watchtower managed block")
    return "".join(lines[starts[0]:stops[0] + 1])


def _main_block(device: dict) -> str:
    return render_managed_peer("", Enrollment(device["operation_id"], device["device"],
                                               device["public_key"], device["address"]))


def _candidate_block(op: dict) -> str:
    return (f"# BEGIN gway-remote replacement: {op['id']}\n[Peer]\n"
            f"# Device = {op['device']}\nPublicKey = {op['public_key']}\n"
            f"AllowedIPs = {op['address']}\n# END gway-remote replacement: {op['id']}\n")


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class Replacements:
    def __init__(self, provisioner):
        self.p = provisioner
        self.ledger = provisioner.ledger

    def _grant(self, db, secret, device, *, consumed=False):
        if not isinstance(secret, str) or not TOKEN.fullmatch(secret):
            raise EnrollmentRejected("replacement rejected")
        row = db.execute(
            "SELECT s.*, i.device AS invited_device, i.purpose, i.replace_authorized, "
            "i.expires_at AS invitation_expiry, i.revoked_at AS invitation_revoked, "
            "i.consumed_at AS invitation_consumed FROM bootstrap_sessions s "
            "JOIN invitations i ON i.id=s.invitation_id WHERE s.session_hash=?",
            (_digest(secret),),
        ).fetchone()
        if (not row or row["device"] != device or row["invited_device"] != device
                or row["purpose"] != "enroll" or row["replace_authorized"] != 1
                or row["revoked_at"] or row["invitation_revoked"]
                or min(row["expires_at"], row["invitation_expiry"]) <= _now()
                or (not consumed and (row["consumed_at"] or row["invitation_consumed"]))):
            raise EnrollmentRejected("replacement rejected")
        return dict(row)

    def _operation(self, db, secret, device, key, ident, *, consumed=False):
        grant = self._grant(db, secret, device, consumed=consumed)
        row = db.execute("SELECT * FROM replacements WHERE id=? AND session_hash=?",
                         (ident, _digest(secret))).fetchone()
        if not row or row["device"] != device or row["public_key"] != key:
            raise EnrollmentRejected("replacement rejected")
        if (grant["consumed_at"] or grant["invitation_consumed"]) and row["state"] not in TERMINAL:
            raise EnrollmentRejected("replacement rejected")
        return dict(row)

    def _get(self, ident):
        with self.ledger._connect() as db:
            return dict(db.execute("SELECT * FROM replacements WHERE id=?", (ident,)).fetchone())

    def _advance(self, op, state):
        with self.ledger._transaction() as db:
            db.execute("UPDATE replacements SET state=?,updated_at=? WHERE id=?",
                       (state, _now(), op["id"]))
        op["state"] = state

    def _node(self, db, op, *, identity=True):
        row = db.execute("SELECT * FROM devices WHERE device=?", (op["device"],)).fetchone()
        if not row or dict(row) != json.loads(op["old_device"]):
            raise EnrollmentFailure("replacement device changed; operator review required")
        if identity:
            host = db.execute("SELECT * FROM host_identities WHERE device=?", (op["device"],)).fetchone()
            if (dict(host) if host else None) != json.loads(op["old_identity"]):
                raise EnrollmentFailure("replacement attestation changed; operator review required")

    def _backup(self, op):
        path = Path(op["backup_path"])
        self.p.backups.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.p.backups.is_symlink() or self.p.backups.stat().st_mode & 0o077:
            raise EnrollmentFailure("unsafe Watchtower backup directory")
        if not path.exists():
            current = self.p.config.read_text(encoding="utf-8")
            if hashlib.sha256(current.encode()).hexdigest() != op["config_digest"]:
                raise EnrollmentFailure("replacement backup missing; operator review required")
            fd, temporary = tempfile.mkstemp(prefix=".replacement-", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(current)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, path)
                _sync_directory(path.parent)
            finally:
                Path(temporary).unlink(missing_ok=True)
        if (path.is_symlink() or path.stat().st_mode & 0o077
                or path.stat().st_uid != os.geteuid()
                or hashlib.sha256(path.read_bytes()).hexdigest() != op["config_digest"]):
            raise EnrollmentFailure("unsafe or damaged replacement backup")

    def _inspect(self, op, *, final=False):
        """Allow only recorded partial states and exact owned peer identities."""
        current = self.p.config.read_text(encoding="utf-8")
        old = json.loads(op["old_device"])
        new = {**old, "operation_id": op["id"], "public_key": op["public_key"], "address": op["address"]}
        main = _block(current, MANAGED_BEGIN + op["device"], MANAGED_END + op["device"])
        candidate = _block(current, f"# BEGIN gway-remote replacement: {op['id']}",
                           f"# END gway-remote replacement: {op['id']}")
        if main != _main_block(old) and not (final and main == _main_block(new)):
            raise EnrollmentFailure("replacement managed peer changed")
        if candidate is not None and candidate != _candidate_block(op):
            raise EnrollmentFailure("replacement candidate changed")
        if old["public_key"] == op["public_key"] and candidate is not None:
            raise EnrollmentFailure("unexpected same-key replacement candidate")
        configured = _peers(current)
        runtime = self.p.wireguard.peer_snapshot()
        targets = {old["public_key"], op["public_key"]}
        if ({k: v for k, v in configured.items() if k not in targets}
                != {k: v for k, v in runtime.items() if k not in targets}):
            raise EnrollmentFailure("Watchtower runtime/config drift; operator review required")
        expected = {old["public_key"]: (old["address"],), op["public_key"]: (op["address"],)}
        for peers in (configured, runtime):
            for key in targets & peers.keys():
                if peers[key] != expected[key]:
                    raise EnrollmentFailure("replacement peer ownership changed")
            for key, addresses in peers.items():
                if key in targets:
                    continue
                for address in addresses:
                    for owned in (old["address"], op["address"]):
                        if ip_network(address).version == ip_network(owned).version and ip_network(address).overlaps(ip_network(owned)):
                            raise EnrollmentFailure("replacement address ownership changed")
        if not final and runtime.get(old["public_key"]) != (old["address"],):
            raise EnrollmentFailure("current replacement peer unavailable")
        return current, old, new, candidate, runtime

    def prepare(self, secret, device, key, *, ssh_host_key=None):
        validate_enrollment({"device": device, "public_key": key, "token": secret})
        with self.p._thread_lock, self.p._config_lock():
            with self.ledger._connect() as db:
                self._grant(db, secret, device)
            self.recover_locked()
            with self.ledger._transaction() as db:
                grant = self._grant(db, secret, device)
                previous = db.execute("SELECT * FROM replacements WHERE session_hash=?", (_digest(secret),)).fetchone()
                if previous:
                    if previous["public_key"] != key or previous["state"] in TERMINAL:
                        raise EnrollmentRejected("replacement rejected")
                    op = dict(previous)
                    self._node(db, op)
                    identity = json.loads(op["old_identity"])
                else:
                    if db.execute("SELECT 1 FROM replacements WHERE device=? AND state NOT IN ('committed','rolled_back')", (device,)).fetchone():
                        raise EnrollmentRejected("replacement rejected")
                    peer = db.execute("SELECT * FROM devices WHERE device=? AND state='active'", (device,)).fetchone()
                    if not peer or not db.execute("SELECT 1 FROM operations WHERE id=? AND state='committed'", (peer["operation_id"],)).fetchone():
                        raise EnrollmentRejected("replacement rejected")
                    peer = dict(peer)
                    host = db.execute("SELECT * FROM host_identities WHERE device=?", (device,)).fetchone()
                    identity = dict(host) if host else None
                    if identity and (identity["state"] != "active" or identity["wireguard_identity"] != peer["public_key"] or identity["valid_until"] <= _now()):
                        raise EnrollmentRejected("replacement rejected")
                    if db.execute("SELECT 1 FROM devices WHERE public_key=? AND device!=?", (key, device)).fetchone() or db.execute("SELECT 1 FROM replacements WHERE public_key=? AND state NOT IN ('committed','rolled_back')", (key,)).fetchone():
                        raise EnrollmentRejected("replacement rejected")
                    if self.p.config.is_symlink() or self.p.config.stat().st_mode & 0o077 or self.p.config.stat().st_uid != os.geteuid():
                        raise EnrollmentFailure("unsafe Watchtower configuration")
                    current = self.p.config.read_text(encoding="utf-8")
                    if not current.endswith("\n") or _block(current, MANAGED_BEGIN + device, MANAGED_END + device) != _main_block(peer):
                        raise EnrollmentFailure("replacement requires exact managed peer ownership")
                    configured = _peers(current)
                    runtime = self.p.wireguard.peer_snapshot()
                    if configured != runtime or configured.get(peer["public_key"]) != (peer["address"],):
                        raise EnrollmentFailure("Watchtower runtime/config drift; operator review required")
                    if key != peer["public_key"] and key in configured:
                        raise EnrollmentRejected("replacement rejected")
                    occupied = [v for values in configured.values() for v in values]
                    address = peer["address"] if key == peer["public_key"] else self.ledger._allocate(db, occupied)
                    for public_key, addresses in configured.items():
                        if public_key == peer["public_key"]:
                            continue
                        for occupied_address in addresses:
                            for owned in (peer["address"], address):
                                if ip_network(occupied_address).version == 4 and ip_network(occupied_address).overlaps(ip_network(owned)):
                                    raise EnrollmentFailure("replacement address ownership changed")
                    ident = secrets.token_hex(16)
                    now = _now()
                    op = dict(id=ident, device=device, session_hash=_digest(secret), invitation_id=grant["invitation_id"],
                              public_key=key, address=address, old_device=json.dumps(peer, sort_keys=True),
                              old_identity=json.dumps(identity, sort_keys=True), state="reserved",
                              backup_path=str(self.p.backups / f"replacement-{ident}.conf"),
                              config_digest=hashlib.sha256(current.encode()).hexdigest(),
                              handshake_after=int(time.time()),
                              expires_at=min(grant["expires_at"], grant["invitation_expiry"]),
                              created_at=now, updated_at=now)
                    # Validate attestation before reserving anything.
                    self._host(identity, ssh_host_key)
                    columns = ",".join(op)
                    db.execute(f"INSERT INTO replacements({columns}) VALUES({','.join('?' for _ in op)})", tuple(op.values()))
                self._host(identity, ssh_host_key)
            self._prepare(op)
            return self.receipt(self._get(op["id"]))

    @staticmethod
    def _host(identity, supplied):
        # Replacement preserves prior trust, including the absence of a binding.
        if (identity is not None and supplied != identity["host_public_key"]) or (identity is None and supplied is not None):
            raise EnrollmentRejected("replacement rejected")

    def _prepare(self, op):
        if op["state"] not in {"reserved", "prepared"}:
            raise EnrollmentRejected("replacement rejected")
        self._backup(op)
        with self.ledger._connect() as db:
            self._node(db, op)
        current, old, new, candidate, runtime = self._inspect(op)
        if old["public_key"] != op["public_key"]:
            if candidate is None:
                if op["public_key"] in runtime:
                    raise EnrollmentFailure("unexpected replacement runtime peer")
                self.p._write(current + _candidate_block(op))
            if op["public_key"] not in runtime:
                self.p.wireguard.set_peer(op["public_key"], op["address"])
            self._inspect(op)
            if self.p.wireguard.peer_snapshot().get(op["public_key"]) != (op["address"],):
                raise EnrollmentFailure("replacement runtime verification failed")
        self._advance(op, "prepared")

    def acknowledge(self, secret, device, key, ident):
        with self.p._thread_lock, self.p._config_lock():
            with self.ledger._transaction() as db:
                op = self._operation(db, secret, device, key, ident, consumed=True)
                if op["state"] == "committed":
                    return self.receipt(op)
                if op["state"] not in {"prepared", "acknowledged"}:
                    raise EnrollmentRejected("replacement rejected")
                self._node(db, op)
                if op["state"] == "prepared":
                    self._inspect(op)
                    handshake = self.p.wireguard.latest_handshake(key)
                    now = int(time.time())
                    if not op["handshake_after"] < handshake <= now or now - handshake > 180:
                        raise EnrollmentRejected("replacement activation unverified")
                    if self.p.wireguard.peer_snapshot().get(key) != (op["address"],):
                        raise EnrollmentRejected("replacement activation unverified")
                    db.execute("UPDATE replacements SET state='acknowledged',updated_at=? WHERE id=?", (_now(), ident))
                    op["state"] = "acknowledged"
            self._commit(op)
            return self.receipt(self._get(ident))

    def _commit(self, op):
        self._backup(op)
        with self.ledger._connect() as db:
            self._node(db, op)
        current, old, new, candidate, runtime = self._inspect(op, final=True)
        if runtime.get(op["public_key"]) != (op["address"],):
            raise EnrollmentFailure("acknowledged replacement peer unavailable")
        if old["public_key"] != op["public_key"]:
            if candidate:
                desired = current.replace(_candidate_block(op), "", 1).replace(_main_block(old), _main_block(new), 1)
                self.p._write(desired)
            elif _block(current, MANAGED_BEGIN + op["device"], MANAGED_END + op["device"]) != _main_block(new):
                raise EnrollmentFailure("acknowledged replacement configuration unavailable")
            if old["public_key"] in runtime:
                self.p.wireguard.remove_peer(old["public_key"])
            if self.p.wireguard.peer_snapshot().get(old["public_key"]) is not None:
                raise EnrollmentFailure("old replacement peer retirement unverified")
        if _peers(self.p.config.read_text()) != self.p.wireguard.peer_snapshot():
            raise EnrollmentFailure("replacement runtime/config verification failed")
        with self.ledger._transaction() as db:
            self._node(db, op)
            now = _now()
            invitation = db.execute("SELECT token_hash FROM invitations WHERE id=?", (op["invitation_id"],)).fetchone()
            db.execute("INSERT INTO operations(id,device,public_key,address,token_hash,state,backup_path,detail,created_at,updated_at) VALUES(?,?,?,?,?,'committed',?,'replacement',?,?)",
                       (op["id"], op["device"], op["public_key"], op["address"], invitation[0], op["backup_path"], op["created_at"], now))
            db.execute("UPDATE devices SET public_key=?,address=?,operation_id=? WHERE device=?",
                       (op["public_key"], op["address"], op["id"], op["device"]))
            db.execute("UPDATE host_identities SET wireguard_identity=?,operation_id=?,enrollment_binding=? WHERE device=?",
                       (op["public_key"], op["id"], hashlib.sha256(op["invitation_id"].encode()).hexdigest(), op["device"]))
            db.execute("UPDATE invitations SET consumed_at=? WHERE id=?", (now, op["invitation_id"]))
            db.execute("UPDATE bootstrap_sessions SET consumed_at=? WHERE session_hash=?", (now, op["session_hash"]))
            db.execute("UPDATE replacements SET state='committed',updated_at=? WHERE id=?", (now, op["id"]))

    def rollback(self, secret, device, key, ident):
        with self.p._thread_lock, self.p._config_lock():
            with self.ledger._connect() as db:
                op = self._operation(db, secret, device, key, ident, consumed=True)
            if op["state"] == "committed":
                raise EnrollmentRejected("replacement already committed")
            if op["state"] != "rolled_back":
                self._rollback(op)
            return self.receipt(self._get(ident))

    def _rollback(self, op):
        self._backup(op)
        with self.ledger._connect() as db:
            self._node(db, op, identity=False)
        current, old, new, candidate, runtime = self._inspect(op, final=True)
        self._advance(op, "rolling_back")
        if old["public_key"] != op["public_key"]:
            desired = current
            if candidate:
                desired = desired.replace(candidate, "", 1)
            elif _block(current, MANAGED_BEGIN + op["device"], MANAGED_END + op["device"]) == _main_block(new):
                desired = desired.replace(_main_block(new), _main_block(old), 1)
            if desired != current:
                self.p._write(desired)
            if old["public_key"] not in runtime:
                self.p.wireguard.set_peer(old["public_key"], old["address"])
            if self.p.wireguard.peer_snapshot().get(old["public_key"]) != (old["address"],):
                raise EnrollmentFailure("replacement rollback peer unverified")
            if op["public_key"] in runtime:
                self.p.wireguard.remove_peer(op["public_key"])
        if _peers(self.p.config.read_text()) != self.p.wireguard.peer_snapshot():
            raise EnrollmentFailure("replacement rollback runtime/config mismatch")
        with self.ledger._transaction() as db:
            now = _now()
            db.execute("UPDATE replacements SET state='rolled_back',updated_at=? WHERE id=?", (now, op["id"]))
            # Retain the authenticated receipt until expiry; never permit reuse.
            db.execute("UPDATE invitations SET consumed_at=? WHERE id=?", (now, op["invitation_id"]))
            db.execute("UPDATE bootstrap_sessions SET consumed_at=? WHERE session_hash=?", (now, op["session_hash"]))

    def status(self, secret, device, key, ident):
        with self.ledger._connect() as db:
            return self.receipt(self._operation(db, secret, device, key, ident, consumed=True))

    @staticmethod
    def receipt(op):
        old = json.loads(op["old_device"])
        return {"protocol": PROTOCOL, "operation_id": op["id"], "device": op["device"],
                "public_key": op["public_key"], "address": op["address"], "state": op["state"],
                "activation_after": op["handshake_after"], "expires_at": op["expires_at"],
                "rekey": old["public_key"] != op["public_key"],
                "old_peer_retired": op["state"] == "committed" and old["public_key"] != op["public_key"],
                "ssh_identity_preserved": True}

    def recover_locked(self):
        """Resume durable intent; never infer activation from a prepared peer."""
        with self.ledger._connect() as db:
            pending = [dict(row) for row in db.execute("SELECT * FROM replacements WHERE state NOT IN ('committed','rolled_back') ORDER BY created_at")]
        recovered = 0
        for op in pending:
            with self.ledger._connect() as db:
                row = db.execute(
                    "SELECT s.expires_at,s.revoked_at,i.expires_at AS invitation_expiry,"
                    "i.revoked_at AS invitation_revoked FROM bootstrap_sessions s "
                    "JOIN invitations i ON i.id=s.invitation_id WHERE s.session_hash=?",
                    (op["session_hash"],),
                ).fetchone()
            cancelled = (not row or row["revoked_at"] or row["invitation_revoked"]
                         or min(row["expires_at"], row["invitation_expiry"]) <= _now())
            if op["state"] == "acknowledged":
                # The activation decision was accepted while authorization was
                # live. Finish it even when a restart crosses the expiry time.
                self._commit(op)
                recovered += 1
            elif op["state"] == "rolling_back" or cancelled:
                self._rollback(op)
                recovered += 1
            else:
                was_reserved = op["state"] == "reserved"
                self._prepare(op)
                recovered += was_reserved
        return recovered
