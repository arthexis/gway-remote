"""Read-only Watchtower node-onboarding diagnosis (issue #549 phase C).

The enrollment snapshot, root-owned execute.json and pinned SSH material are
existing authorities. A doctor never grants eligibility, runs SSH, starts a
worker, issues OAuth tokens, opens a writable ledger or claims remote health.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from . import node_registry_inventory
from .watchtower_exec_service import CONFIG as EXEC_CONFIG
from .watchtower_exec_transport import DEFAULT_LEDGER, PinnedNode

MAX_EXEC_CONFIG = 4096
MAX_LEDGER = 128 * 1024 * 1024
_PIN_FIELDS = frozenset(("node", "address", "ssh_host_alias", "known_hosts",
                         "identity_file", "host_key_sha256", "remote_user"))
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _private_config(node, path=EXEC_CONFIG, *, pinned_factory=PinnedNode,
                    required_owner=0):
    """Inspect only the configured pin, never create a transport or use SSH.

    Strict root-owned file evidence; no unchecked addresses/paths from the
    caller and no private material in the returned report.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {"state": "not_configured"}, None
    except OSError:
        return {"state": "unknown"}, None
    try:
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                    or info.st_uid != required_owner
                    or info.st_mode & 0o022 or not 0 < info.st_size <= MAX_EXEC_CONFIG):
                return {"state": "unsafe_configuration"}, None
            raw = stream.read(MAX_EXEC_CONFIG + 1)
        if len(raw) > MAX_EXEC_CONFIG:
            return {"state": "unsafe_configuration"}, None
        data = json.loads(raw)
        if type(data) is not dict or data.get("enabled") is not True:
            return {"state": "not_enabled"}, None
        if set(data) == _PIN_FIELDS | {"enabled"}:
            entries = [{key: data[key] for key in _PIN_FIELDS}]
        elif set(data) == {"enabled", "nodes"} and type(data["nodes"]) is list:
            entries = data["nodes"]
        else:
            return {"state": "invalid_configuration"}, None
        if not 1 <= len(entries) <= 32 or any(
                type(entry) is not dict or set(entry) != _PIN_FIELDS
                or type(entry["node"]) is not str for entry in entries):
            return {"state": "invalid_configuration"}, None
        names = [entry["node"] for entry in entries]
        if len(set(names)) != len(names):
            return {"state": "invalid_configuration"}, None
        matches = [entry for entry in entries if entry["node"] == node]
        if not matches:
            return {"state": "not_pinned"}, None
        item = matches[0]
        if item["ssh_host_alias"] != node:
            return {"state": "binding_mismatch"}, None
        # The existing PinnedNode verifier checks authorized key fingerprint,
        # owner/mode and address. Do not relax or reimplement its security.
        pinned_factory(node=node, wireguard_address=item["address"],
                       ssh_host_alias=item["ssh_host_alias"],
                       known_hosts=Path(item["known_hosts"]),
                       identity_file=Path(item["identity_file"]),
                       host_key_sha256=item["host_key_sha256"],
                       remote_user=item["remote_user"])
        return {"state": "pin_validated_offline"}, {
            "address": item["address"],
            "host_key_sha256": item["host_key_sha256"],
        }
    except (ValueError, TypeError, KeyError, UnicodeError):
        return {"state": "invalid_configuration"}, None
    except (OSError, PermissionError):
        return {"state": "unknown"}, None


def _ledger_evidence(node, host_key_sha256, path=DEFAULT_LEDGER):
    """Consult only checkpointed, immutable SQLite bytes. Never touch WAL/SHM.

    Historical success is evidence of a previous authenticated node result,
    not proof of the current executor, recipe, user manager or SSH connectivity.
    """
    output = ({"state": "unknown", "evidence": "not_checked"},
              {"state": "unknown", "evidence": "no_current_result"})
    if type(host_key_sha256) is not str or not _SHA.fullmatch(host_key_sha256):
        return output
    path = Path(path)
    try:
        parent = path.parent.lstat()
        info = path.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
                or parent.st_mode & 0o077 or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & 0o077
                or not 0 < info.st_size <= MAX_LEDGER or path.is_symlink()):
            return ({"state": "untrusted"}, output[1])
        # immutable=1 is strictly read-only even with a WAL-mode database. It
        # may omit recent uncheckpointed jobs, which must remain unknown.
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1",
                             uri=True, timeout=2) as connection:
            rows = connection.execute(
                "SELECT updated_at FROM requests WHERE node=? AND host_key_sha256=? "
                "AND state='succeeded' AND command NOT LIKE 'deployment:%' "
                "ORDER BY updated_at DESC LIMIT 1", (node, host_key_sha256)).fetchall()
        ledger = {"state": "readable_checkpoint_only"}
        if not rows:
            return ledger, {"state": "unknown", "evidence": "no_current_result"}
        timestamp = rows[0][0]
        when = datetime.fromisoformat(timestamp)
        if when.tzinfo is None or when > datetime.now(timezone.utc):
            return ledger, {"state": "unknown", "evidence": "invalid_historical_timestamp"}
        return ledger, {"state": "historical_succeeded", "observed_at": timestamp,
                        "evidence": "private_ledger_checkpoint"}
    except (OSError, PermissionError, ValueError, sqlite3.Error):
        return output


def diagnose_node(node, *, inventory_loader=node_registry_inventory.load,
                  pin_inspector=_private_config, ledger_inspector=_ledger_evidence):
    """Explain readiness without taking any execution or enrollment action."""
    if type(node) is not str or not node_registry_inventory.NODE.fullmatch(node):
        raise ValueError("invalid_node")
    report = {
        "schema": 1, "node": node, "source": "watchtower_local_read_only",
        "enrollment": {"state": "unknown"},
        "attestation": {"state": "unknown"},
        "reachability": {"state": "unknown"},
        "eligibility": {"state": "unknown"},
        "pinned_ssh": {"state": "unknown"},
        "executor": {"state": "unknown", "identity": None},
        "ansible_recipe": {"state": "unknown", "evidence": "node_not_queried"},
        "systemd_bus": {"state": "unknown", "evidence": "node_not_queried"},
        "request_ledger": {"state": "unknown", "evidence": "not_checked"},
        "terminal_result": {"state": "unknown", "evidence": "no_current_result"},
        "installed_release": {"state": "unverified", "sha": None},
        "operational": {"state": "unverified", "reason": "no_live_result"},
        "ready_for_operator_test": False,
    }
    try:
        rows = inventory_loader()["nodes"]
        if type(rows) is not list:
            raise ValueError("invalid inventory")
    except (OSError, ValueError, PermissionError, KeyError, TypeError):
        report["enrollment"] = {"state": "unknown", "reason": "inventory_unavailable"}
        return report
    matches = [row for row in rows if type(row) is dict and row.get("node") == node]
    if len(matches) != 1:
        report["enrollment"] = {"state": "not_registered"}
        return report
    record = matches[0]
    if (record.get("registered") is not True or
            record.get("registration_state") != "active"):
        report["enrollment"] = {"state": "inactive"}
        return report
    report["enrollment"] = {"state": "active"}
    attested = record.get("identity_verified") is True
    report["attestation"] = {"state": "verified" if attested else "not_verified"}
    reachable = record.get("reachable")
    report["reachability"] = {"state": reachable if reachable == "reachable" else "unknown"}
    granted = record.get("execute_eligible") is True
    report["eligibility"] = {"state": "granted" if granted else "not_granted",
                             "source": "watchtower_enrollment_ledger"}
    pin, binding = pin_inspector(node)
    report["pinned_ssh"] = pin
    if binding is not None and record.get("address") != binding["address"]:
        report["pinned_ssh"] = {"state": "binding_mismatch"}
        binding = None
    if binding is not None:
        ledger, historical = ledger_inspector(node, binding["host_key_sha256"])
        report["request_ledger"] = ledger
        report["terminal_result"] = historical
    report["ready_for_operator_test"] = bool(
        attested and reachable == "reachable" and granted
        and report["pinned_ssh"]["state"] == "pin_validated_offline")
    # Even a prior terminal success cannot assert that the node is operational
    # now. Only a separate fresh authenticated node_result may establish that.
    return report


def format_diagnosis(report):
    return "\n".join((
        "Node: " + report["node"],
        "Enrollment: " + report["enrollment"]["state"],
        "Attestation: " + report["attestation"]["state"],
        "Reachability: " + report["reachability"]["state"],
        "Watchtower eligibility: " + report["eligibility"]["state"],
        "Pinned SSH: " + report["pinned_ssh"]["state"] + " (offline only)",
        "Ansible recipe installed: " + report["ansible_recipe"]["state"],
        "Executor identity: " + report["executor"]["state"],
        "Systemd user bus: " + report["systemd_bus"]["state"],
        "Request ledger: " + report["request_ledger"]["state"],
        "Terminal result: " + report["terminal_result"]["state"],
        "Installed SHA: unverified",
        "Execution health: " + report["operational"]["state"],
        "Ready for separately authorized test: " +
        ("yes" if report["ready_for_operator_test"] else "no"),
    ))
