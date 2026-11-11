"""Phase D: bounded, local-only Git/inventory/installed drift evidence.

No external Git fetch, deploy, systemd mutation, SSH, sudo, provider tool
invocation or credential access. Checkout comparisons are local hints, never
a statement about the authenticated GitHub main revision.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess

from .mcp_installed_providers import discover_installed_providers, INSTALL_DIR
from .mcp_deployment_broker import status as deployment_status
from .mcp_deployment_contract import validate_deployment
from .deployment_policy import INVENTORY

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_RETIRED = ("gway-remote-watch.timer", "gway-remote-watch.service",
            "gway-remote-deploy.service")
_SOURCE_FILES = ("ansible/roles/gway_remote/tasks/main.yml",
                 "ansible/roles/gway_remote/tasks/node-mcp-deploy.yml",
                 "ansible/playbooks/watchtower-mcp.yml",
                 "ansible/playbooks/watchtower-enrollment-refresh.yml")
_ORIGINS = ("https://github.com/arthexis/gway-remote",
            "https://github.com/arthexis/gway-remote.git",
            "git@github.com:arthexis/gway-remote.git")
_MAX_INVENTORY = 65536
_MAX_MANIFEST = 262144
_MAX_SOURCE = 131072
_RELEASE = Path("/opt/gway-mcp")
_PROPOSALS = {
    "DRIFT_INVENTORY": "review_inventory_with_operator",
    "DRIFT_RELEASE": "review_release_activation",
    "DRIFT_RELEASE_CONTENT": "review_immutable_release",
    "DRIFT_RETIRED_UNIT": "review_retired_unit_policy",
    "DRIFT_REACTIVATION_RULE": "review_checked_in_ansible_task",
    "MISSING_REQUIRED_UNIT": "review_preprovisioned_unit",
    "UNTRUSTED_INVENTORY": "inspect_inventory_permissions",
    "INVALID_RELEASE_EVIDENCE": "inspect_release_provenance",
    "INVALID_PROVIDER_REGISTRY": "inspect_node_owned_manifests",
    "GIT_SOURCE_UNKNOWN": "verify_remote_main_independently",
    "INVENTORY_UNKNOWN": "inspect_local_inventory",
    "RELEASE_UNKNOWN": "inspect_local_release",
    "SERVICE_UNKNOWN": "check_systemd_with_existing_identity",
    "SOURCE_RULES_UNKNOWN": "review_local_git_checkout",
}


def _finding(code, *, status="unknown", evidence="not_verified"):
    return {"code": code, "status": status, "evidence": evidence,
            "proposed_action": _PROPOSALS[code]}


def _owned_bytes(path, *, maximum, owner=0):
    """Bounded, symlink-resistant metadata read, not a content trust anchor."""
    p = Path(path)
    parent = p.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != owner
            or parent.st_mode & 0o022 or p.parent.is_symlink()):
        raise PermissionError("untrusted_parent")
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner
                or info.st_mode & 0o022 or not 0 < info.st_size <= maximum):
            raise PermissionError("untrusted_file")
        data = stream.read(maximum + 1)
    if not 0 < len(data) <= maximum:
        raise ValueError("oversized_or_empty")
    return data


def _read_inventory(path=INVENTORY, *, reader=_owned_bytes):
    try:
        data = reader(path, maximum=_MAX_INVENTORY)
    except FileNotFoundError:
        return {"state": "unknown", "digest": None, "reason": "missing"}
    except (OSError, ValueError, PermissionError):
        return {"state": "untrusted", "digest": None, "reason": "unsafe_or_inaccessible"}
    return {"state": "validated_local_file", "digest": hashlib.sha256(data).hexdigest()}


def _git_source(checkout, *, run=subprocess.run):
    """Read one local, operator-selected Git checkout; never fetch remote HEAD."""
    unknown = {"state": "unknown", "revision": None, "inventory_digest": None,
               "rules": "unknown", "evidence": "no_authenticated_git_remote"}
    if checkout is None:
        return unknown
    base = Path(checkout)
    try:
        if not base.is_dir() or base.is_symlink():
            return unknown
        env = {"PATH": "/usr/bin:/bin", "GIT_TERMINAL_PROMPT": "0",
               "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
        def get(*args, maximum=1024):
            completed = run(["git", "-C", str(base), *args],
                            capture_output=True, timeout=5, check=False, env=env)
            if completed.returncode or len(completed.stdout) > maximum:
                raise ValueError("unavailable_git_evidence")
            return completed.stdout
        sha = get("rev-parse", "--verify", "HEAD").decode("ascii").strip()
        branch = get("symbolic-ref", "-q", "--short", "HEAD").decode("ascii").strip()
        origin = get("remote", "get-url", "origin").decode("utf-8").strip()
        if not _SHA.fullmatch(sha) or branch != "main" or origin not in _ORIGINS:
            return unknown
        inventory = get("show", "HEAD:ansible/inventory/deployment.yml",
                        maximum=_MAX_INVENTORY)
        if not inventory:
            return unknown
        # Fetch only checked-in fixed Ansible sources. None is executed.
        files = [get("show", "HEAD:" + path, maximum=_MAX_SOURCE).decode("utf-8")
                 for path in _SOURCE_FILES]
        return {"state": "local_checkout", "revision": sha,
                "inventory_digest": hashlib.sha256(inventory).hexdigest(),
                "rules": _retired_rules(files),
                "evidence": "local_checkout_not_remote_verified"}
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        return unknown


def _retired_rules(sources):
    """Conservative static scan of explicit, non-comment Ansible service tasks.

    Dynamic templates/includes cannot be fully resolved and do not prove
    absence of future reactivation rules.
    """
    found = set()
    for content in sources:
        stripped = "\n".join(line for line in content.splitlines()
                              if not line.lstrip().startswith("#"))
        for task in re.split(r"(?m)^\s*- name:\s+", stripped):
            if not re.search(r"ansible\.builtin\.(?:systemd|systemd_service):", task):
                continue
            if not re.search(r"(?m)^\s*(?:enabled:\s*(?:true|yes)|state:\s*(?:started|restarted))\s*$", task):
                continue
            for unit in _RETIRED:
                if unit in task:
                    found.add(unit)
    return sorted(found)


def _release_observation(root=_RELEASE, *, reader=_owned_bytes, owner=0):
    """Observe selected MCP pointer and partial immutable manifest integrity.

    Checks selected revision + launcher hash, not service health or all files.
    """
    unknown = {"state": "unknown", "selected_sha": None, "evidence": "not_verified"}
    root = Path(root)
    try:
        for d in (root, root / "releases"):
            info = d.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner
                    or info.st_mode & 0o022 or d.is_symlink()):
                return {"state": "invalid", "selected_sha": None, "evidence": "unsafe_root"}
        current = root / "current"
        pointer = current.lstat()
        if not stat.S_ISLNK(pointer.st_mode) or pointer.st_uid != owner:
            return {"state": "invalid", "selected_sha": None, "evidence": "unsafe_pointer"}
        relative = os.readlink(current)
        if not re.fullmatch(r"releases/[0-9a-f]{40}", relative):
            return {"state": "invalid", "selected_sha": None, "evidence": "unsafe_pointer"}
        sha = relative.split("/")[1]
        release = root / "releases" / sha
        meta = release.lstat()
        if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid != owner
                or meta.st_mode & 0o022 or release.is_symlink()):
            return {"state": "invalid", "selected_sha": None, "evidence": "unsafe_release"}
        manifest = json.loads(reader(release / "manifest.json",
                                     maximum=_MAX_MANIFEST, owner=owner))
        if (type(manifest) is not dict or set(manifest) != {"revision", "sha256"}
                or manifest["revision"] != sha
                or type(manifest["sha256"]) is not dict
                or not 0 < len(manifest["sha256"]) <= 512
                or "run.py" not in manifest["sha256"]
                or not all(type(k) is str and type(v) is str
                           and _HASH.fullmatch(v) for k,v in manifest["sha256"].items())):
            return {"state": "invalid", "selected_sha": None, "evidence": "invalid_manifest"}
        run = reader(release / "run.py", maximum=65536, owner=owner)
        if hashlib.sha256(run).hexdigest() != manifest["sha256"]["run.py"]:
            return {"state": "invalid", "selected_sha": None, "evidence": "launcher_digest_mismatch"}
        return {"state": "selected_partial_verified", "selected_sha": sha,
                "evidence": "root_owned_pointer_manifest_launcher"}
    except FileNotFoundError:
        return unknown
    except (OSError, ValueError, UnicodeError, TypeError, KeyError, PermissionError):
        return {"state": "unknown", "selected_sha": None, "evidence": "unsafe_or_unreadable"}


def _providers(*, discover=discover_installed_providers, receipt=deployment_status):
    """Manifests are node authority. Receipts are historical, not active SHA."""
    try:
        regs = discover(INSTALL_DIR)
        rows = []
        for item in regs:
            historical = "not_applicable"
            if item.deployment is not None:
                historical = "unknown"
                try:
                    val = receipt(item.source_id, resolve=lambda _: validate_deployment(
                        item.deployment))
                    if type(val) is dict and val.get("state") in (
                            "never_run", "running", "succeeded", "failed"):
                        historical = val["state"]
                except (OSError, ValueError, TypeError, KeyError, PermissionError):
                    pass
            rows.append({"source": item.source_id, "manifest_revision": item.revision,
                         "receipt": historical, "installed_release": "unverified"})
        return {"state": "manifest_validated", "providers": rows}
    except (OSError, ValueError, TypeError, KeyError, PermissionError):
        return {"state": "unknown", "providers": []}


def _unit(unit, *, user=False, run=subprocess.run):
    """Inspect only a fixed unit. Never invoke systemd changes."""
    argv = ["systemctl"] + (["--user"] if user else []) + [
        "show", unit, "--no-pager",
        "--property=LoadState,ActiveState,UnitFileState"]
    try:
        res = run(argv, capture_output=True, text=True, timeout=4, check=False)
        if res.returncode or len(res.stdout) > 2048:
            return {"state": "unknown"}
        fields = {}
        for line in res.stdout.splitlines():
            if "=" in line:
                k,v = line.split("=",1)
                if k in ("LoadState", "ActiveState", "UnitFileState"):
                    fields[k]=v
        if set(fields) != {"LoadState", "ActiveState", "UnitFileState"}:
            return {"state": "unknown"}
        if (fields["LoadState"] not in ("loaded","not-found","masked","error")
                or fields["ActiveState"] not in ("active","inactive","failed","activating","deactivating")
                or fields["UnitFileState"] not in (
                    "enabled","disabled","static","masked","linked","linked-runtime",
                    "generated","transient","indirect","alias","bad","")):
            return {"state": "unknown"}
        return {"state": "observed", "load": fields["LoadState"],
                "active": fields["ActiveState"], "enablement": fields["UnitFileState"]}
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return {"state": "unknown"}


def _services(*, node=None, unit_reader=_unit):
    hostname = node or socket.gethostname().split(".")[0]
    output = {"state": "observed", "current": {}, "retired": {}}
    for unit in _RETIRED:
        output["retired"][unit] = unit_reader(unit)
    # Only the existing gway-001 identity can observe the user-service bus.
    if hostname == "gway-001" and pwd.getpwuid(os.geteuid()).pw_name == "arthe":
        output["current"]["gway-remote-mcp.service"] = unit_reader(
            "gway-remote-mcp.service", user=True)
    elif hostname == "gway-001":
        output["current"]["gway-remote-mcp.service"] = {"state": "unknown"}
    else:
        output["current"]["gway-mcp-gateway.service"] = unit_reader(
            "gway-mcp-gateway.service")
        output["current"]["gway-mcp-link.service"] = unit_reader(
            "gway-mcp-link.service")
    return output


def classify(source, inventory, release, providers, services):
    """Pure, stable, sanitized findings. Partial evidence is never a green bill."""
    findings = []
    def add(code, status="unknown", evidence="not_verified"):
        findings.append(_finding(code, status=status, evidence=evidence))
    if source["state"] != "local_checkout":
        add("GIT_SOURCE_UNKNOWN")
        add("SOURCE_RULES_UNKNOWN")
    elif source["rules"]:
        for _ in source["rules"]:
            add("DRIFT_REACTIVATION_RULE", "drift", "local_checkout_rule")
    if inventory["state"] == "untrusted":
        add("UNTRUSTED_INVENTORY", "drift", "local_file_permissions")
    elif inventory["state"] != "validated_local_file":
        add("INVENTORY_UNKNOWN")
    elif source["inventory_digest"] and source["inventory_digest"] != inventory["digest"]:
        add("DRIFT_INVENTORY", "drift", "local_checkout_only")
    if release["state"] == "invalid":
        add("INVALID_RELEASE_EVIDENCE", "drift", release["evidence"])
    elif release["state"] != "selected_partial_verified":
        add("RELEASE_UNKNOWN")
    elif source["revision"] and source["revision"] != release["selected_sha"]:
        add("DRIFT_RELEASE", "drift", "local_checkout_only")
    if providers["state"] != "manifest_validated":
        add("INVALID_PROVIDER_REGISTRY", "unknown")
    for unit, value in services["retired"].items():
        if value["state"] == "observed" and (
                value["active"] == "active" or value["enablement"] == "enabled"):
            add("DRIFT_RETIRED_UNIT", "drift", "local_systemd_observation")
        elif value["state"] != "observed":
            add("SERVICE_UNKNOWN")
    for unit, value in services["current"].items():
        if value["state"] == "observed" and value["load"] == "not-found":
            add("MISSING_REQUIRED_UNIT", "drift", "local_systemd_observation")
        elif value["state"] != "observed":
            add("SERVICE_UNKNOWN")
    # Never call it fully healthy: even a systemd 'active' state does not
    # validate OAuth, worker identity, provider availability, or source HEAD.
    if any(f["status"] == "drift" for f in findings):
        verdict = "drift_detected"
    elif findings:
        verdict = "incomplete"
    else:
        verdict = "no_observed_drift_not_health_verified"
    return {"state": verdict, "findings": findings}


def doctor(*, checkout=None, source_reader=_git_source,
           inventory_reader=_read_inventory, release_reader=_release_observation,
           providers_reader=_providers, services_reader=_services):
    """Collect bounded evidence; all source paths and units remain read-only."""
    source = source_reader(checkout)
    inventory = inventory_reader()
    release = release_reader()
    providers = providers_reader()
    services = services_reader()
    evaluation = classify(source, inventory, release, providers, services)
    return {"schema": 1, "kind": "gway-remote/drift-doctor",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "source": source, "inventory": inventory, "release": release,
            "providers": providers, "services": services,
            "result": evaluation}


def format_report(report):
    rows = ["GWay Remote drift doctor (local read-only)",
            "Source: " + report["source"]["state"],
            "Inventory: " + report["inventory"]["state"],
            "MCP release: " + report["release"]["state"],
            "Provider manifests: " + report["providers"]["state"],
            "Verdict: " + report["result"]["state"]]
    for finding in report["result"]["findings"]:
        rows.append(f'  {finding["code"]}: {finding["proposed_action"]} '
                    f'({finding["evidence"]})')
    rows.append("No changes applied. Checkout HEAD is not verified GitHub main; "
                "selected release is not runtime health.")
    return "\n".join(rows)
