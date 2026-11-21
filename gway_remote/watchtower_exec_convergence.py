"""Root-only central execution pin and grant convergence.

No remote bootstrap or TOFU. Trust flows only from Watchtower's authoritative
enrollment ledger and the existing private gateway SSH material. Snapshot writes
are compare-and-swap and journalled; unaccepted transactions block further
grants until explicitly recovered.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import ipaddress
import json
import re
import os
from pathlib import Path
import shutil
import stat
import subprocess

from .host_identity import validate_attestation
from .node_inspection import snapshot_from_path
from .node_registry_inventory import LEDGER, NODE, build, publish
from .watchtower_exec_service import CONFIG
from .watchtower_exec_eligibility import set_eligibility
from .watchtower_pin_002 import (
    _atomic_file, _directory, _file, _metadata, _parse_config,
    _key_for_alias, _new_private, _journal, _sync_dir,
    MAX_CONFIG, MAX_KNOWN,
)

STATE = Path("/var/lib/gway-remote/watchtower-exec-convergence")
GATEWAY = "gway-mcp-gateway.service"
FIELDS = {"node", "address", "ssh_host_alias", "known_hosts",
          "identity_file", "host_key_sha256", "remote_user"}


class ConvergenceRefused(ValueError):
    """No config/trust/eligibility mutation can be justified."""


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _operator_lease(state_root, *, owner=0):
    """A process-lifetime nonblocking lock across grant, revoke and recovery.

    The durable .active directory is a crash journal marker, not proof that a
    process is still alive. flock adds this distinction without another service
    or ledger; the permanent private file never carries credentials.
    """
    root = Path(state_root)
    _directory(root, owner=owner)
    if stat.S_IMODE(root.lstat().st_mode) != 0o700:
        raise ConvergenceRefused("transaction directory must be private")
    fd = os.open(root / ".operator-lock",
                 os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise ConvergenceRefused("unsafe operator lock file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConvergenceRefused("another operator transaction is active") from exc
        return fd
    except BaseException:
        os.close(fd)
        raise


def _entry_and_bytes(node, enabled, config, known, snapshot):
    """Pure multi-node plan. All inputs are from trusted local files."""
    if type(node) is not str or not NODE.fullmatch(node):
        raise ConvergenceRefused("invalid enrolled node")
    if enabled and not re.fullmatch(r"gway-[0-9]{3}", node):
        # Named standalone satellites are WireGuard-only until an explicitly
        # reviewed SSH execution policy is implemented for them.
        raise ConvergenceRefused("central restricted relay supports gway-NNN only")
    settings = _parse_config(config)
    rows = settings["nodes"]
    if not isinstance(snapshot, dict) or snapshot.get("schema") != 2:
        raise ConvergenceRefused("invalid authoritative enrollment snapshot")
    enrolled = [r for r in snapshot.get("nodes", []) if
                isinstance(r, dict) and r.get("node") == node]
    if len(enrolled) != 1:
        raise ConvergenceRefused("node is missing or ambiguous")
    current = enrolled[0]
    if enabled:
        if current.get("state") != "active":
            raise ConvergenceRefused("node not actively enrolled")
        binding = validate_attestation(current.get("host_identity"), node=node)
        host_key = binding["host_key"]
        address = ipaddress.ip_interface(current["address"])
        if (address.version != 4 or address.network.prefixlen != 32
                or not address.ip.is_private):
            raise ConvergenceRefused("invalid verified management address")
        digest = _digest(base64.b64decode(host_key.split()[1], validate=True))
    else:
        host_key = None
        digest = None
        address = None

    known_lines = known.decode("ascii").splitlines()
    for entry in rows:
        if type(entry) is not dict or set(entry) != FIELDS or entry["ssh_host_alias"] != entry["node"]:
            raise ConvergenceRefused("unsafe pinned node entry")
        if _key_for_alias(known, entry["node"]) != entry["host_key_sha256"]:
            raise ConvergenceRefused("existing host pin mismatch")

    matches = [r for r in rows if r["node"] == node]
    if len(matches) > 1:
        raise ConvergenceRefused("ambiguous existing transport")
    prior = matches[0] if matches else None
    if enabled:
        shared_known = {r["known_hosts"] for r in rows}
        shared_identity = {r["identity_file"] for r in rows}
        if len(shared_known) != 1 or len(shared_identity) != 1:
            raise ConvergenceRefused("mixed gateway SSH authorities")
        path_known, path_identity = next(iter(shared_known)), next(iter(shared_identity))
        if prior and (prior["host_key_sha256"] != digest or
                      prior["address"] != str(address.ip) or
                      prior["remote_user"] != "gway-relay"):
            raise ConvergenceRefused("pinned node changed; explicit rotation required")
        entries = [line.split() for line in known_lines if line and
                   not line.lstrip().startswith("#") and line.split()]
        aliases = [parts for parts in entries if
                   parts[0] == node or node in parts[0].split(",")]
        if aliases:
            if len(aliases) != 1 or _key_for_alias(known, node) != digest:
                raise ConvergenceRefused("existing node host pin differs")
            new_known = known
        else:
            new_known = known + (b"" if known.endswith(b"\n") else b"\n") + (
                node + " " + host_key + "\n").encode("ascii")
        if not prior:
            rows.append({
                "node": node, "address": str(address.ip), "ssh_host_alias": node,
                "known_hosts": path_known, "identity_file": path_identity,
                "host_key_sha256": digest, "remote_user": "gway-relay",
            })
    else:
        if prior and len(rows) <= 1:
            raise ConvergenceRefused("refuse to remove last active gateway transport")
        settings["nodes"] = [r for r in rows if r["node"] != node]
        new_known = known  # Keep historical pin for explicit rotation detection.

    new_config = (json.dumps(settings, separators=(",", ":"), sort_keys=True)
                  + "\n").encode("utf-8") if (not prior and enabled) or (prior and not enabled) else config
    if len(new_config) > MAX_CONFIG or len(new_known) > MAX_KNOWN:
        raise ConvergenceRefused("configuration size limit")
    return new_config, new_known


def plan(node, enabled, *, config=CONFIG, ledger=LEDGER):
    if os.geteuid() != 0 or type(enabled) is not bool:
        raise ConvergenceRefused("root and explicit action required")
    snapshot = snapshot_from_path(ledger)
    original, config_stat = _file(Path(config), uid=0, maximum=MAX_CONFIG)
    settings = _parse_config(original)
    paths = {r["known_hosts"] for r in settings["nodes"]}
    identities = {r["identity_file"] for r in settings["nodes"]}
    if len(paths) != 1 or len(identities) != 1:
        raise ConvergenceRefused("gateway identity mismatch")
    known_path = Path(next(iter(paths)))
    identity_path = Path(next(iter(identities)))
    if any(not p.is_absolute() or ".." in p.parts for p in (known_path, identity_path)):
        raise ConvergenceRefused("untrusted gateway SSH paths")
    known_stat = known_path.lstat()
    if known_stat.st_uid <= 0:
        raise ConvergenceRefused("private SSH material must belong to gateway user")
    known, known_stat = _file(known_path, uid=known_stat.st_uid,
                             maximum=MAX_KNOWN, private=True)
    identity_stat = _metadata(identity_path, uid=known_stat.st_uid)
    if identity_stat.st_mode & 0o077:
        raise ConvergenceRefused("gateway identity must be private")
    new_config, new_known = _entry_and_bytes(node, enabled, original, known, snapshot)
    return {"config": (Path(config), original, new_config, config_stat),
            "known": (known_path, known, new_known, known_stat),
            "node": node, "enabled": enabled}


def _restore_files(stage, node):
    record = json.loads((stage / "journal.json").read_text())
    if (record.get("node") != node or record.get("schema") != 1
            or type(record.get("prior_eligible")) is not bool
            or record.get("state") != "prepared"
            or set(record.get("targets", {})) != {"config", "known"}):
        raise ConvergenceRefused("untrusted transaction journal")
    snapshots = {}
    for kind in ("config", "known"):
        item = record["targets"][kind]
        file = Path(item["path"])
        if (not file.is_absolute() or ".." in file.parts
                or (kind == "config" and file != CONFIG)):
            raise ConvergenceRefused("rollback target path mismatch")
        before, _ = _file(stage / (kind + ".before"), uid=0,
                           maximum=MAX_CONFIG if kind == "config" else MAX_KNOWN,
                           private=True)
        after, _ = _file(stage / (kind + ".after"), uid=0,
                          maximum=MAX_CONFIG if kind == "config" else MAX_KNOWN,
                          private=True)
        if _digest(before) != item["before"] or _digest(after) != item["after"]:
            raise ConvergenceRefused("untrusted before/after image")
        latest, info = _file(file, uid=item["uid"],
                             maximum=MAX_CONFIG if kind == "config" else MAX_KNOWN,
                             private=kind == "known")
        if (_digest(latest) not in (item["before"], item["after"]) or
                stat.S_IMODE(info.st_mode) != item["mode"] or info.st_gid != item["gid"]):
            raise ConvergenceRefused("concurrent edit requires manual reconciliation")
        snapshots[kind] = file, before, latest, info
    for kind in ("config", "known"):
        path, before, latest, info = snapshots[kind]
        if before != latest:
            _atomic_file(path, before, info)


def _claim(plan_data, state, *, prior_eligible):
    _directory(state.parent, owner=0)
    os.mkdir(state, mode=0o700)  # Exclusive; stale journal must be recovered.
    _sync_dir(state.parent)
    targets = {}
    for kind in ("config", "known"):
        path, before, after, info = plan_data[kind]
        _new_private(state / (kind + ".before"), before)
        _new_private(state / (kind + ".after"), after)
        targets[kind] = {"path": str(path), "uid": info.st_uid, "gid": info.st_gid,
                         "mode": stat.S_IMODE(info.st_mode),
                         "before": _digest(before), "after": _digest(after)}
    _sync_dir(state)
    _journal(state, {"schema": 1, "node": plan_data["node"],
                     "state": "prepared", "prior_eligible": prior_eligible,
                     "targets": targets})


def _activate_files(plan_data):
    for kind in ("known", "config"):
        path, before, after, info = plan_data[kind]
        latest, current = _file(path, uid=info.st_uid,
                                maximum=MAX_CONFIG if kind == "config" else MAX_KNOWN,
                                private=kind == "known")
        if (latest != before or current.st_ino != info.st_ino or
                current.st_gid != info.st_gid or
                stat.S_IMODE(current.st_mode) != stat.S_IMODE(info.st_mode)):
            raise ConvergenceRefused("concurrent gateway config modification")
        if before != after:
            _atomic_file(path, after, info)


def _finish_stage(stage):
    # All children created by our own root-owned exclusive transaction.
    for filename in ("journal.json", "config.before", "config.after",
                     "known.before", "known.after"):
        (stage / filename).unlink(missing_ok=True)
    stage.rmdir()


def verify_gateway_limits(node, *, runner=subprocess.run):
    """Probe strict SSH as the actual unprivileged gateway service user.

    Root-run checks are insufficient: its pinned identity may have different
    file ownership and produce false negatives. The command is fixed and
    returns a bounded, correlated, read-only limits result.
    """
    if type(node) is not str or not NODE.fullmatch(node):
        raise ConvergenceRefused("invalid limits target")
    result = runner(
        ["/usr/bin/sudo", "-n", "-u", "gway-mcp-gateway",
         "/usr/bin/env", "PYTHONPATH=/opt/gway-mcp/current",
         "/usr/bin/python3", "-m", "gway_remote",
         "node", "verify", node, "--json"],
        capture_output=True, text=True, timeout=25, check=True,
    )
    if type(result.stdout) is not str or len(result.stdout) > 4096:
        raise ConvergenceRefused("invalid gateway limits result")
    try:
        report = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise ConvergenceRefused("invalid gateway limits JSON") from exc
    if (type(report) is not dict or report.get("node") != node
            or report.get("schema") != 1 or report.get("stage") != "limits"
            or report.get("status") != "succeeded"
            or type(report.get("concurrent_jobs_per_node")) is not int
            or not 1 <= report["concurrent_jobs_per_node"] <= 8):
        raise ConvergenceRefused("strict-pinned gateway limits failed")
    return True


def converge(action, node, *, config=CONFIG, ledger=LEDGER, state_root=STATE,
             set_grant=set_eligibility, inventory_builder=build, publisher=publish,
             runner=subprocess.run):
    """One serialized operator transaction; no TOFU or unattended recovery."""
    if action not in ("grant", "revoke") or type(node) is not str or not NODE.fullmatch(node):
        raise ConvergenceRefused("invalid execution action")
    if os.geteuid() != 0:
        raise ConvergenceRefused("root required")
    enable = action == "grant"
    state_root = Path(state_root)
    if not state_root.exists():
        _directory(state_root.parent, owner=0)
        state_root.mkdir(mode=0o700)
    _directory(state_root, owner=0)
    if stat.S_IMODE(state_root.lstat().st_mode) != 0o700:
        raise ConvergenceRefused("transaction directory must be private")

    # Acquire the cross-node lock BEFORE planning, inspecting eligibility, or
    # taking the idempotent shortcut. Otherwise a stale plan may race a grant
    # for a different node, and a pending journal could be silently bypassed.
    stage = state_root / node
    global_lock = state_root / ".active"
    operator_fd = _operator_lease(state_root)
    try:
        os.mkdir(global_lock, mode=0o700)
    except BaseException:
        os.close(operator_fd)
        raise
    try:
        if stage.exists():
            raise ConvergenceRefused("pending transaction requires operator recovery")
        p = plan(node, enable, config=config, ledger=ledger)
        from .node_registry_inventory import _grants
        prior = _grants(ledger).get(node, ("", False))[1]
        changed = any(p[kind][1] != p[kind][2] for kind in ("config", "known"))
        if not changed and prior == enable:
            # A no-op must still prove the actual service transport, but only
            # after exclusion of unresolved transactions.
            if enable:
                verify_gateway_limits(node, runner=runner)
            return {"node": node, "eligible": enable, "transport_configured": enable,
                    "limits_verified": enable, "terminal_execution_verified": False,
                    "changed": False}

        try:
            _claim(p, stage, prior_eligible=prior)
        except Exception:
            # No live state has been modified before _claim returns; clean
            # incomplete preparations rather than leave an unrecoverable
            # journal-less lock. Unknown extra files still fail closed.
            if stage.is_dir():
                _finish_stage(stage)
            raise
        try:
            if enable:
                set_grant(node, True, ledger=ledger)
            _activate_files(p)
            if not enable:
                set_grant(node, False, ledger=ledger)
            publisher(inventory_builder(ledger=ledger, probe=True))
            runner(["systemctl", "restart", GATEWAY], capture_output=True,
                   text=True, timeout=90, check=True)
            runner(["systemctl", "is-active", "--quiet", GATEWAY],
                   capture_output=True, text=True, timeout=10, check=True)
            if enable:
                verify_gateway_limits(node, runner=runner)
            _finish_stage(stage)
            return {"node": node, "eligible": enable, "transport_configured": enable,
                    "limits_verified": enable, "terminal_execution_verified": False}
        except Exception:
            # A crash leaves the private journal; synchronous failure attempts
            # byte-faithful rollback, preserving the lock if recovery fails.
            try:
                _restore_files(stage, node)
                set_grant(node, prior, ledger=ledger)
                publisher(inventory_builder(ledger=ledger, probe=True))
                runner(["systemctl", "restart", GATEWAY], capture_output=True,
                       text=True, timeout=90, check=True)
                _finish_stage(stage)
            except Exception:
                pass  # Operator must inspect and explicitly recover.
            raise
    finally:
        # Release only when no unresolved journal remains. This also covers
        # read-only planning failures and successful idempotent operations.
        try:
            if not stage.exists():
                global_lock.rmdir()
        finally:
            os.close(operator_fd)


def recover(node, *, state_root=STATE, ledger=LEDGER,
            set_grant=set_eligibility, inventory_builder=build, publisher=publish,
            runner=subprocess.run):
    """Operator-only rollback, mutually exclusive with a still-running grant."""
    if os.geteuid() != 0 or not isinstance(node, str) or not NODE.fullmatch(node):
        raise ConvergenceRefused("root and exact node required")
    state_root = Path(state_root)
    # Recovery can reconstruct a missing crash marker, but never operate while
    # a grant/revoke/recovery is active. The operator lease is kernel-released
    # on process death, unlike the durable crash journal marker.
    fd = _operator_lease(state_root)
    try:
        active = state_root / ".active"
        if not active.exists():
            active.mkdir(mode=0o700)
        else:
            _directory(active, owner=0)
        stage = state_root / node
        _directory(stage, owner=0)
        data = json.loads((stage / "journal.json").read_text())
        if data.get("schema") != 1 or data.get("node") != node:
            raise ConvergenceRefused("invalid recovery journal")
        _restore_files(stage, node)
        set_grant(node, data["prior_eligible"], ledger=ledger)
        publisher(inventory_builder(ledger=ledger, probe=True))
        runner(["systemctl", "restart", GATEWAY], capture_output=True,
               text=True, timeout=90, check=True)
        _finish_stage(stage)
        active.rmdir()
        return {"node": node, "recovered": True, "eligible": data["prior_eligible"]}
    finally:
        os.close(fd)
