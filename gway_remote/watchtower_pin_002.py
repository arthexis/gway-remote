"""Watchtower-only, journalled initial SSH pin for already attested gway-002.

No SSH, Ansible, service reload, enrollment, OAuth or AgentOps action. The
default CLI operation is read-only. Two POSIX files cannot be atomically
replaced together; durable before/after images permit explicit recovery.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import stat
import tempfile

from .host_identity import validate_attestation, validate_public_key
from .node_inspection import snapshot_from_path
from . import node_registry_inventory
from .watchtower_exec_service import CONFIG

NODE = "gway-002"
HOST_KEY = Path("/etc/gway-remote/verified-gway-002-host.pub")
STATE = Path("/var/lib/gway-remote/watchtower-pin-002")
LEDGER = node_registry_inventory.LEDGER
INVENTORY = node_registry_inventory.SNAPSHOT
FIELDS = frozenset(("node", "address", "ssh_host_alias", "known_hosts",
                    "identity_file", "host_key_sha256", "remote_user"))
SHA = re.compile(r"^[0-9a-f]{64}$")
_APPROVAL = "I_ACCEPT_GWAY_002_WATCHTOWER_PIN"
ABB_NODE = "ocpp-abb-1"
ABB_HOST_KEY = Path("/etc/gway-remote/verified-ocpp-abb-1-host.pub")
ABB_STATE = Path("/var/lib/gway-remote/watchtower-pin-abb")
ABB_APPROVAL = "I_ACCEPT_ABB_WATCHTOWER_PIN"
ABB_ROLLBACK = "I_ACCEPT_ABB_PIN_ROLLBACK"
MAX_CONFIG = 4096
MAX_KNOWN = 65536


class PinRefused(ValueError):
    """A precondition or recovery invariant failed; never improvise trust."""


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _directory(path, *, owner=None):
    info = path.lstat()  # no follow for the directory itself
    if (not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022
            or (owner is not None and info.st_uid != owner)):
        raise PinRefused("unsafe configuration directory")
    return info


def _file(path, *, uid, maximum, private=False):
    _directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != uid or info.st_mode & 0o022
                or (private and info.st_mode & 0o077)
                or not 0 < info.st_size <= maximum):
            raise PinRefused("unsafe pinned file metadata")
        raw = os.read(fd, maximum + 1)
        if len(raw) != info.st_size or len(raw) > maximum:
            raise PinRefused("file changed while reading")
        return raw, info
    finally:
        os.close(fd)


def _metadata(path, *, uid, private=True):
    _directory(path.parent)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != uid or info.st_mode & 0o022
            or (private and info.st_mode & 0o077)):
        raise PinRefused("unsafe private SSH identity metadata")
    return info


def _key_for_alias(known, alias):
    matches = []
    for line in known.decode("ascii").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split()
        # Combined aliases or hashed aliases must not silently match.
        if parts[0] == alias or alias in parts[0].split(","):
            matches.append(parts)
    if len(matches) != 1 or len(matches[0]) < 3:
        raise PinRefused("missing or ambiguous existing SSH host pin")
    if matches[0][1] not in ("ssh-ed25519", "ecdsa-sha2-nistp256",
                              "rsa-sha2-512", "ssh-rsa"):
        raise PinRefused("unsupported existing SSH pin")
    try:
        return _digest(base64.b64decode(matches[0][2], validate=True))
    except (ValueError, base64.binascii.Error) as exc:
        raise PinRefused("invalid existing SSH pin") from exc


def _parse_config(raw):
    value = json.loads(raw)
    if (type(value) is not dict or set(value) != {"enabled", "nodes"}
            or value["enabled"] is not True or type(value["nodes"]) is not list
            or not 1 <= len(value["nodes"]) < 32):
        raise PinRefused("expected existing multi-node configuration")
    seen = set()
    for entry in value["nodes"]:
        if (type(entry) is not dict or set(entry) != FIELDS
                or type(entry["node"]) is not str or entry["node"] in seen
                or entry["ssh_host_alias"] != entry["node"]
                or entry["remote_user"] != "gway-relay"):
            raise PinRefused("invalid existing node configuration")
        seen.add(entry["node"])
    return value


def _attested_key(node, path):
    raw, _ = _file(path, uid=0, maximum=2048)
    lines = raw.decode("ascii").strip().splitlines()
    if len(lines) != 1:
        raise PinRefused("ambiguous verified host key")
    parts = lines[0].split()
    if len(parts) not in (2, 3):
        raise PinRefused("invalid verified host key")
    key = validate_public_key(" ".join(parts[:2]))
    ledger = snapshot_from_path(LEDGER)  # existing read-only SQLite reader
    rows = [x for x in ledger["nodes"] if x.get("node") == node]
    if len(rows) != 1 or rows[0].get("state") != "active":
        raise PinRefused("missing active Watchtower enrollment")
    record = validate_attestation(rows[0].get("host_identity"), node=node)
    if record["host_key"] != key:
        raise PinRefused("verified host key differs from current attestation")
    return key, rows[0]["address"]


def plan(*, service_uid, config=CONFIG, host_key=None,
         inventory=INVENTORY, node=NODE):
    """Pure read-side preparation; never connects to SSH or mutates any file."""
    if node not in (NODE, ABB_NODE):
        raise PinRefused("unsupported pin target")
    if host_key is None:
        host_key = ABB_HOST_KEY if node == ABB_NODE else HOST_KEY
    if type(service_uid) is not int or service_uid <= 0:
        raise PinRefused("explicit nonroot gateway service UID required")
    original_config, config_stat = _file(config, uid=0, maximum=MAX_CONFIG)
    parsed = _parse_config(original_config)
    if any(x["node"] == node for x in parsed["nodes"]):
        raise PinRefused(f"{node} is already configured; manual review required")
    paths = {x["known_hosts"] for x in parsed["nodes"]}
    identities = {x["identity_file"] for x in parsed["nodes"]}
    if len(paths) != 1 or len(identities) != 1:
        raise PinRefused("existing SSH transports use conflicting private files")
    known_path = Path(next(iter(paths)))
    identity_path = Path(next(iter(identities)))
    for path in (known_path, identity_path):
        if not path.is_absolute() or ".." in path.parts:
            raise PinRefused("untrusted SSH path")
    original_known, known_stat = _file(
        known_path, uid=service_uid, maximum=MAX_KNOWN, private=True)
    _metadata(identity_path, uid=service_uid)
    if node.encode("ascii") in original_known:
        # Conservative: any pre-existing reference needs operator reconciliation.
        raise PinRefused(f"existing {node} pin requires manual reconciliation")
    for entry in parsed["nodes"]:
        if (not SHA.fullmatch(entry["host_key_sha256"])
                or _key_for_alias(original_known, entry["node"])
                != entry["host_key_sha256"]):
            raise PinRefused("an existing node pin is no longer valid")

    host_pub, ledger_address = _attested_key(node, host_key)
    enrolled_ip = ipaddress.ip_interface(ledger_address)
    if enrolled_ip.version != 4 or enrolled_ip.network.prefixlen != 32:
        raise PinRefused("invalid enrolled WireGuard /32")
    current = node_registry_inventory.load(inventory)
    matches = [x for x in current["nodes"] if x["node"] == node]
    if (len(matches) != 1 or matches[0]["registered"] is not True
            or matches[0]["identity_verified"] is not True
            or matches[0]["execute_eligible"] is not True
            or matches[0]["reachable"] != "reachable"
            or matches[0]["address"] != str(enrolled_ip.ip)):
        raise PinRefused("fresh enrolled execution eligibility or address denied")

    digest = _digest(base64.b64decode(host_pub.split()[1], validate=True))
    appended = ("" if original_known.endswith(b"\n") else "\n").encode("ascii")
    new_known = original_known + appended + (node + " " + host_pub + "\n").encode("ascii")
    entry = {
        "node": node,
        "address": str(enrolled_ip.ip),
        "ssh_host_alias": node,
        "known_hosts": str(known_path),
        "identity_file": str(identity_path),
        "host_key_sha256": digest,
        "remote_user": "gway-relay",
    }
    parsed["nodes"].append(entry)
    new_config = (json.dumps(parsed, sort_keys=True, separators=(",", ":"))
                  + "\n").encode("utf-8")
    if len(new_config) > MAX_CONFIG or len(new_known) > MAX_KNOWN:
        raise PinRefused("target configuration exceeds installed service limit")
    return {
        "config": (Path(config), original_config, new_config, config_stat),
        "known": (known_path, original_known, new_known, known_stat),
        "existing_nodes": tuple(x["node"] for x in parsed["nodes"] if x["node"] != node),
        "pin_digest": digest,
    }


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _new_private(path, raw):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _atomic_file(path, raw, info):
    _directory(path.parent)
    fd, name = tempfile.mkstemp(prefix=".gway-002-pin-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            staged_info = os.fstat(out.fileno())
            if (staged_info.st_uid, staged_info.st_gid) != (info.st_uid, info.st_gid):
                os.fchown(out.fileno(), info.st_uid, info.st_gid)
            os.fchmod(out.fileno(), stat.S_IMODE(info.st_mode))
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)  # atomic *per file*, not across both files
        _sync_dir(path.parent)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


def _journal(root, payload):
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
               + "\n").encode("ascii")
    dest = root / "journal.json"
    if not dest.exists():
        _new_private(dest, encoded)
    else:
        # Journal update itself is atomic + fsynced.
        fd, name = tempfile.mkstemp(prefix=".journal-", dir=root)
        try:
            with os.fdopen(fd, "wb") as out:
                os.fchmod(out.fileno(), 0o600)
                out.write(encoded)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, dest)
        finally:
            if os.path.lexists(name):
                os.unlink(name)
    _sync_dir(root)


def _read_journal(root, *, node=NODE):
    raw, _ = _file(root / "journal.json", uid=0, maximum=8192, private=True)
    data = json.loads(raw)
    if (type(data) is not dict or data.get("schema") != 1
            or data.get("node") != node
            or data.get("state") not in ("prepared", "pending_acceptance",
                                         "rolled_back")):
        raise PinRefused("invalid transaction journal")
    return data


def _recover(root, *, expected_paths=None, node=NODE):
    """Restore both original images; tolerate a crash after either swap."""
    data = _read_journal(root, node=node)
    if data["state"] == "rolled_back":
        return "already_rolled_back"
    if (set(data) != {"schema", "node", "state", "targets"}
            or set(data["targets"]) != {"config", "known"}):
        raise PinRefused("unexpected journal fields")
    snapshots = {}
    for kind in ("config", "known"):
        row = data["targets"][kind]
        if set(row) != {"path", "uid", "gid", "mode", "before", "after"}:
            raise PinRefused("unexpected transaction target")
        target = Path(row["path"])
        if (kind == "config" and target != CONFIG
                or kind == "known" and (not target.is_absolute()
                                         or ".." in target.parts)
                or (expected_paths is not None and target != expected_paths[kind])):
            raise PinRefused("journal target mismatch")
        prior, _ = _file(root / (kind + ".before"), uid=0,
                         maximum=MAX_CONFIG if kind == "config" else MAX_KNOWN,
                         private=True)
        after, _ = _file(root / (kind + ".after"), uid=0,
                         maximum=MAX_CONFIG if kind == "config" else MAX_KNOWN,
                         private=True)
        if _digest(prior) != row["before"] or _digest(after) != row["after"]:
            raise PinRefused("backup or staged file digest mismatch")
        current, info = _file(target, uid=row["uid"],
                              maximum=MAX_CONFIG if kind == "config" else MAX_KNOWN,
                              private=(kind == "known"))
        if (_digest(current) not in (row["before"], row["after"])
                or info.st_gid != row["gid"]
                or stat.S_IMODE(info.st_mode) != row["mode"]):
            raise PinRefused("concurrent or untrusted target modification")
        snapshots[kind] = (target, prior, current, info)
    # Remove the new node from root config first; then restore known_hosts.
    for kind in ("config", "known"):
        target, before, current, info = snapshots[kind]
        if before != current:
            _atomic_file(target, before, info)
    _journal(root, {**data, "state": "rolled_back"})
    return "rolled_back"


def apply(*, service_uid, approval, relay_confirmed, state=None, node=NODE):
    """Explicit operator-only publication. Does NOT reload gateway or test SSH."""
    if node not in (NODE, ABB_NODE):
        raise PinRefused("unsupported pin target")
    if state is None:
        state = ABB_STATE if node == ABB_NODE else STATE
    if approval != (ABB_APPROVAL if node == ABB_NODE else _APPROVAL) or relay_confirmed is not True:
        raise PinRefused("explicit relay acceptance and pin authorization required")
    if os.geteuid() != 0:
        raise PinRefused("Watchtower pin application requires root")
    p = plan(service_uid=service_uid) if node == NODE else plan(service_uid=service_uid, node=node)
    _directory(state.parent, owner=0)
    # mkdir is a one-shot exclusive transaction lock. Any residue blocks a
    # new operation until explicit recovery/review.
    os.mkdir(state, mode=0o700)
    _sync_dir(state.parent)
    targets = {}
    for kind in ("config", "known"):
        target, before, after, info = p[kind]
        _new_private(state / (kind + ".before"), before)
        _new_private(state / (kind + ".after"), after)
        targets[kind] = {
            "path": str(target), "uid": info.st_uid, "gid": info.st_gid,
            "mode": stat.S_IMODE(info.st_mode),
            "before": _digest(before), "after": _digest(after),
        }
    _sync_dir(state)
    _journal(state, {"schema": 1, "node": node, "state": "prepared",
                     "targets": targets})
    try:
        # Compare-and-swap reads prevent overwriting changed files.
        for kind in ("config", "known"):
            target, before, _, info = p[kind]
            latest, meta = _file(target, uid=info.st_uid,
                                 maximum=MAX_CONFIG if kind == "config" else MAX_KNOWN,
                                 private=(kind == "known"))
            if latest != before or meta.st_ino != info.st_ino:
                raise PinRefused("config changed since preflight")
        # Known host goes first so existing configs remain usable between swaps.
        # Recheck each original file immediately before its OWN replacement:
        # an operator can alter config after both initial preflight reads.
        # This narrows, but cannot eliminate, an uncooperative rename race.
        for kind in ("known", "config"):
            target, before, after, info = p[kind]
            latest, current = _file(target, uid=info.st_uid,
                                    maximum=MAX_CONFIG if kind == "config" else MAX_KNOWN,
                                    private=(kind == "known"))
            if (latest != before or current.st_ino != info.st_ino
                    or current.st_gid != info.st_gid
                    or stat.S_IMODE(current.st_mode) != stat.S_IMODE(info.st_mode)):
                raise PinRefused("concurrent change before target replacement")
            _atomic_file(target, after, info)
            observed, _ = _file(target, uid=info.st_uid,
                                maximum=MAX_CONFIG if kind == "config" else MAX_KNOWN,
                                private=(kind == "known"))
            if observed != after:
                raise PinRefused("post-write readback mismatch")
        _journal(state, {"schema": 1, "node": node,
                         "state": "pending_acceptance", "targets": targets})
        return "pending_acceptance"
    except Exception:
        try:
            _recover(state, expected_paths={k: p[k][0] for k in ("config", "known")}, node=node)
        except Exception:
            pass  # never mask the original error; recovery remains operator-visible
        raise


def recover(*, state=None, approval, node=NODE):
    if node not in (NODE, ABB_NODE):
        raise PinRefused("unsupported pin target")
    if state is None:
        state = ABB_STATE if node == ABB_NODE else STATE
    if os.geteuid() != 0 or approval != (ABB_ROLLBACK if node == ABB_NODE else "I_ACCEPT_GWAY_002_PIN_ROLLBACK"):
        raise PinRefused("explicit root rollback approval required")
    _directory(state, owner=0)
    return _recover(state, node=node)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Watchtower-only gway-002 pin; no SSH/deploy")
    parser.add_argument("action", choices=("preview", "apply", "recover"))
    parser.add_argument("--node", choices=(NODE, ABB_NODE), default=NODE)
    parser.add_argument("--service-uid", type=int)
    parser.add_argument("--approval", default="")
    parser.add_argument("--relay-confirmed", action="store_true",
                        help="operator assertion of separately verified strict SSH protocol")
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error("Watchtower root operator session required")
    try:
        if args.action == "recover":
            status = recover(approval=args.approval, node=args.node)
        else:
            if args.service_uid is None:
                parser.error("verified gateway service UID required")
            if args.action == "preview":
                result = plan(service_uid=args.service_uid, node=args.node)
                status = "preflight_only"
            else:
                status = apply(service_uid=args.service_uid, approval=args.approval,
                               relay_confirmed=args.relay_confirmed, node=args.node)
        print(json.dumps({"schema": 1, "node": args.node, "status": status,
                          "services_reloaded": False, "execution_verified": False}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error("gway-002 SSH pin refused (inspect offline journal and preconditions)")


if __name__ == "__main__":
    raise SystemExit(main())
