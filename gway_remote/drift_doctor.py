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
_MAX_RELEASE_FILE = 262144
_MAX_RELEASE_TOTAL = 8 * 1024 * 1024
_RELEASE = Path("/opt/gway-mcp")


class _UntrustedFileError(PermissionError):
    """A checked ownership/mode violation, unlike mere read inaccessibility."""


_PROPOSALS = {
    "DRIFT_INVENTORY": "review_inventory_with_operator",
    "DRIFT_RELEASE": "review_release_activation",
    "DRIFT_RELEASE_CONTENT": "review_immutable_release",
    "DRIFT_RETIRED_UNIT": "review_retired_unit_policy",
    "DRIFT_REACTIVATION_RULE": "review_checked_in_ansible_task",
    "MISSING_DECLARED_RULE": "review_missing_checked_in_ansible_rule",
    "DRIFT_REQUIRED_UNIT_INACTIVE": "review_inactive_required_service",
    "DRIFT_REQUIRED_UNIT_DISABLED": "review_disabled_watchtower_service",
    "MISSING_REQUIRED_UNIT": "review_preprovisioned_unit",
    "UNTRUSTED_INVENTORY": "inspect_inventory_permissions",
    "INVALID_RELEASE_EVIDENCE": "inspect_release_provenance",
    "INVALID_PROVIDER_REGISTRY": "inspect_node_owned_manifests",
    "GIT_SOURCE_UNKNOWN": "verify_remote_main_independently",
    "INVENTORY_UNKNOWN": "inspect_local_inventory",
    "RELEASE_UNKNOWN": "inspect_local_release",
    "PROVIDER_REGISTRY_EMPTY": "inspect_node_owned_provider_registry",
    "DRIFT_REQUIRED_UNIT_MASKED": "review_masked_required_unit",
    "SERVICE_UNKNOWN": "check_systemd_with_existing_identity",
    "SOURCE_RULES_UNKNOWN": "review_local_git_checkout",
}


def _finding(code, *, status="unknown", evidence="not_verified", target=None):
    row = {"code": code, "status": status, "evidence": evidence,
           "proposed_action": _PROPOSALS[code]}
    # Only fixed, non-sensitive unit identifiers may appear in findings.
    if target is not None:
        if target not in _RETIRED + ("gway-remote-mcp.service",
                                     "gway-mcp-gateway.service", "gway-mcp-link.service"):
            raise ValueError("invalid_unit_target")
        row["target"] = target
    return row


def _owned_bytes(path, *, maximum, owner=0):
    """Bounded, symlink-resistant metadata read, not a content trust anchor."""
    p = Path(path)
    # Anchor the parent directory and use dir_fd for the final file: a
    # symlink swap between lstat and open must never redirect a privileged read.
    dfd = os.open(p.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parent = os.fstat(dfd)
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != owner
                or parent.st_mode & 0o022):
            raise _UntrustedFileError("untrusted_parent")
        fd = os.open(p.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=dfd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner
                    or info.st_mode & 0o022 or not 0 < info.st_size <= maximum):
                raise _UntrustedFileError("untrusted_file")
            data = stream.read(maximum + 1)
    finally:
        os.close(dfd)
    if not 0 < len(data) <= maximum:
        raise ValueError("oversized_or_empty")
    return data


def _read_inventory(path=INVENTORY, *, reader=_owned_bytes):
    try:
        data = reader(path, maximum=_MAX_INVENTORY)
    except FileNotFoundError:
        return {"state": "unknown", "digest": None, "reason": "missing"}
    except _UntrustedFileError:
        return {"state": "untrusted", "digest": None, "reason": "unsafe_file_metadata"}
    except (OSError, ValueError, PermissionError):
        # EACCES/ENOTDIR/timeout cannot prove the file is unsafe. Avoid a
        # false positive drift classification when permissions prevent a read.
        return {"state": "unknown", "digest": None, "reason": "inaccessible_or_invalid"}
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
        rule_scan = _retired_rules(files)
        return {"state": "local_checkout", "revision": sha,
                "inventory_digest": hashlib.sha256(inventory).hexdigest(),
                "rules": rule_scan["matches"],
                "rules_dynamic": rule_scan["ambiguous"],
                "missing_rules": _missing_required_rules(files),
                "evidence": "local_checkout_not_remote_verified"}
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        return unknown


def _retired_rules(sources):
    """Inspect literal systemd module targets, not names in task prose.

    Templated names/activation states may be runtime-dependent. When a
    retired unit is mentioned but the target cannot be resolved statically,
    expose unknown instead of asserting drift or absence of reactivation.
    """
    found = set()
    ambiguous = False
    for content in sources:
        stripped = "\n".join(line for line in content.splitlines()
                              if not line.lstrip().startswith("#"))
        for task in re.split(r"(?m)^[ \t]*- name:[ \t]+", stripped):
            match = re.search(
                r"(?m)^(?P<indent>[ \t]*)ansible\.builtin\.(?:systemd|systemd_service):[ \t]*$",
                task)
            if match is None:
                continue
            indent = len(match.group("indent"))
            settings = {}
            for line in task[match.end():].splitlines():
                if not line.strip():
                    continue
                depth = len(line) - len(line.lstrip())
                if depth <= indent:
                    break
                if depth == indent + 2 and ":" in line:
                    key, value = line.strip().split(":", 1)
                    if key in ("name", "state", "enabled"):
                        settings[key] = value.strip().strip("'\"")
            target = settings.get("name", "")
            state = settings.get("state", "")
            enabled = settings.get("enabled", "")
            activating = state in ("started", "restarted") or enabled in ("true", "yes")
            dynamic = any("{{" in value or "{%" in value
                          for value in (target, state, enabled))
            if target in _RETIRED and activating:
                found.add(target)
            elif target in _RETIRED and dynamic:
                ambiguous = True
            elif dynamic and any(unit in task for unit in _RETIRED):
                ambiguous = True
            elif not target and any(unit in task for unit in _RETIRED):
                ambiguous = True
    return {"matches": sorted(found), "ambiguous": ambiguous}


def _missing_required_rules(sources):
    """Flag removal of the fixed, reviewed Ansible install/retirement guards.

    This is a bounded static *source* check, not an Ansible inventory parse or
    assertion that the installed units have converged. Any rewritten/dynamic
    implementation requires operator review rather than an automatic repair.
    """
    if len(sources) != len(_SOURCE_FILES):
        raise ValueError("incomplete_reviewed_sources")

    def blocks(source):
        return re.split(r"(?m)^\s*- name:\s+", "\n".join(
            line for line in source.splitlines()
            if not line.lstrip().startswith("#")))

    def has_task(index, module, needle, *, fields=()):
        return any(
            module in task and needle in task
            and all(re.search(r"(?m)^\s*" + re.escape(k)
                              + r":\s*" + re.escape(v) + r"\s*$", task)
                    for k, v in fields)
            for task in blocks(sources[index])
        )

    missing = []
    main = 0
    provider = 1
    watchtower = 2
    # The GitHub Health timer must have install AND both bounded token-state
    # branches. A removed 'disable when no token' is a real future-deploy risk.
    if not (has_task(main, "ansible.builtin.template:", "gway-remote-health.timer")
            and has_task(main, "ansible.builtin.template:", "gway-remote-health.service")
            and has_task(main, "ansible.builtin.systemd:", "gway-remote-health.timer",
                         fields=(("enabled", "true"), ("state", "started")))
            and has_task(main, "ansible.builtin.systemd:", "gway-remote-health.timer",
                         fields=(("enabled", "false"), ("state", "stopped")))):
        missing.append({"target": "gway-remote-health.timer",
                        "evidence": "health_timer_recipe_missing"})
    # The obsolete broker service must remain explicitly stopped AND removed
    # by the existing node-owned provider deployment tasks.
    if not (has_task(provider, "ansible.builtin.systemd:",
                     "gway-remote-deploy.service",
                     fields=(("enabled", "false"), ("state", "stopped")))
            and has_task(provider, "ansible.builtin.file:",
                         "/etc/systemd/system/gway-remote-deploy.service",
                         fields=(("state", "absent"),))):
        missing.append({"target": "gway-remote-deploy.service",
                        "evidence": "retired_service_guard_missing"})
    for unit in ("gway-mcp-link.service", "gway-mcp-gateway.service"):
        if not has_task(watchtower, "ansible.builtin.copy:",
                        "/etc/systemd/system/" + unit):
            missing.append({"target": unit,
                            "evidence": "watchtower_unit_recipe_missing"})
    return missing


def _release_observation(root=_RELEASE, *, reader=_owned_bytes, owner=0):
    """Check selected pointer and every bounded, manifest-listed file.

    Does not prove runtime process mapping, OAuth health, or unlisted files.
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
        def unique_object(pairs):
            result = dict(pairs)
            if len(result) != len(pairs):
                raise ValueError("duplicate_manifest_key")
            return result
        manifest = json.loads(reader(release / "manifest.json",
                                     maximum=_MAX_MANIFEST, owner=owner),
                              object_pairs_hook=unique_object)
        if (type(manifest) is not dict or set(manifest) != {"revision", "sha256"}
                or manifest["revision"] != sha
                or type(manifest["sha256"]) is not dict
                or not 0 < len(manifest["sha256"]) <= 512
                or "run.py" not in manifest["sha256"]
                or not all(type(k) is str and type(v) is str
                           and _HASH.fullmatch(v) for k,v in manifest["sha256"].items())):
            return {"state": "invalid", "selected_sha": None, "evidence": "invalid_manifest"}
        total = 0
        for name, digest in sorted(manifest["sha256"].items()):
            # Fixed release layout emitted by the already-approved stager.
            parts = Path(name).parts
            if (not 0 < len(name) <= 240 or Path(name).is_absolute()
                    or Path(name).as_posix() != name
                    or any(part in (".", "..") or not re.fullmatch(
                        r"[A-Za-z0-9_.-]+", part) for part in parts)
                    or not (name == "run.py" or
                            name.startswith(("gway_remote/", "deploy/mcp-bearer/")))):
                return {"state": "invalid", "selected_sha": None,
                        "evidence": "invalid_manifest"}
            for level in range(1, len(parts)):
                parent = release.joinpath(*parts[:level])
                info = parent.lstat()
                if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner
                        or info.st_mode & 0o022 or parent.is_symlink()):
                    return {"state": "invalid", "selected_sha": None,
                            "evidence": "unsafe_release_path"}
            try:
                data = reader(release / name, maximum=_MAX_RELEASE_FILE, owner=owner)
            except FileNotFoundError:
                return {"state": "invalid", "selected_sha": None,
                        "evidence": "manifest_file_missing"}
            total += len(data)
            if total > _MAX_RELEASE_TOTAL:
                return {"state": "unknown", "selected_sha": None,
                        "evidence": "release_size_limit"}
            if hashlib.sha256(data).hexdigest() != digest:
                return {"state": "invalid", "selected_sha": None,
                        "evidence": ("launcher_digest_mismatch" if name == "run.py"
                                     else "manifest_content_mismatch")}
        return {"state": "selected_manifest_verified", "selected_sha": sha,
                "evidence": "root_owned_manifest_file_digests"}
    except FileNotFoundError:
        return unknown
    except (OSError, ValueError, UnicodeError, TypeError, KeyError, PermissionError):
        return {"state": "unknown", "selected_sha": None, "evidence": "unsafe_or_unreadable"}


def _providers(*, discover=discover_installed_providers, receipt=deployment_status):
    """Manifests are node authority. Receipts are historical, not active SHA."""
    try:
        regs = discover(INSTALL_DIR)
        # The existing parser returns () both when the directory is missing
        # and when it is empty. Neither proves provider registration complete.
        if not regs:
            return {"state": "empty_unverified", "providers": []}
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


def _services(*, node=None, unit_reader=_unit, role=None):
    hostname = node or socket.gethostname().split(".")[0]
    # Never guess 'Watchtower' from not being gway-001: satellites must not
    # be falsely diagnosed as lacking Watchtower-only units.
    if role is None:
        if hostname == "gway-001":
            role = "controller"
        elif (Path("/etc/systemd/system/gway-mcp-link.service").exists()
              or Path("/etc/systemd/system/gway-mcp-gateway.service").exists()):
            role = "watchtower_candidate"
        else:
            role = "unknown"
    if role not in ("controller", "watchtower_candidate", "unknown"):
        raise ValueError("invalid_role")
    output = {"state": "observed", "role": role, "current": {}, "retired": {}}
    for unit in _RETIRED:
        output["retired"][unit] = unit_reader(unit)
    if role == "controller":
        # Never inspect the wrong user's bus or infer service failure from it.
        try:
            is_operator = pwd.getpwuid(os.geteuid()).pw_name == "arthe"
        except (KeyError, OSError):
            is_operator = False
        output["current"]["gway-remote-mcp.service"] = (
            unit_reader("gway-remote-mcp.service", user=True)
            if is_operator else {"state": "unknown"})
    elif role == "watchtower_candidate":
        for unit in ("gway-mcp-gateway.service", "gway-mcp-link.service"):
            output["current"][unit] = unit_reader(unit)
    return output


def classify(source, inventory, release, providers, services):
    """Pure, stable, sanitized findings. Partial evidence is never a green bill."""
    findings = []
    def add(code, status="unknown", evidence="not_verified", target=None):
        findings.append(_finding(code, status=status, evidence=evidence, target=target))
    if source["state"] != "local_checkout":
        add("GIT_SOURCE_UNKNOWN")
        add("SOURCE_RULES_UNKNOWN")
    else:
        for target in source["rules"]:
            add("DRIFT_REACTIVATION_RULE", "drift", "local_checkout_rule", target)
        if source.get("rules_dynamic"):
            add("SOURCE_RULES_UNKNOWN", evidence="dynamic_systemd_rule")
        for missing in source.get("missing_rules", ()):
            add("MISSING_DECLARED_RULE", "drift", missing["evidence"], missing["target"])
    if inventory["state"] == "untrusted":
        add("UNTRUSTED_INVENTORY", "drift", "local_file_permissions")
    elif inventory["state"] != "validated_local_file":
        add("INVENTORY_UNKNOWN")
    elif source["inventory_digest"] and source["inventory_digest"] != inventory["digest"]:
        add("DRIFT_INVENTORY", "drift", "local_checkout_only")
    if release["state"] == "invalid":
        code = ("DRIFT_RELEASE_CONTENT" if release["evidence"] in (
            "launcher_digest_mismatch", "manifest_content_mismatch",
            "manifest_file_missing") else "INVALID_RELEASE_EVIDENCE")
        add(code, "drift", release["evidence"])
    elif release["state"] != "selected_manifest_verified":
        add("RELEASE_UNKNOWN")
    elif source["revision"] and source["revision"] != release["selected_sha"]:
        add("DRIFT_RELEASE", "drift", "local_checkout_only")
    if providers["state"] == "empty_unverified":
        add("PROVIDER_REGISTRY_EMPTY", evidence="no_manifests_observed")
    elif providers["state"] != "manifest_validated":
        add("INVALID_PROVIDER_REGISTRY", "unknown")
    for unit, value in services["retired"].items():
        if value["state"] == "observed" and (
                value["active"] == "active" or value["enablement"] == "enabled"):
            add("DRIFT_RETIRED_UNIT", "drift", "local_systemd_observation", unit)
        elif (value["state"] != "observed" or
              value["load"] == "error" or value["enablement"] == "bad"):
            # A malformed/undetermined systemd unit is not evidence of
            # successful retirement even when ActiveState=inactive.
            add("SERVICE_UNKNOWN", target=unit)
    if services.get("role") == "unknown":
        add("SERVICE_UNKNOWN", evidence="host_role_not_proven")
    for unit, value in services["current"].items():
        if value["state"] != "observed":
            add("SERVICE_UNKNOWN", target=unit)
        elif value["load"] in ("not-found", "masked"):
            add("MISSING_REQUIRED_UNIT", "drift", "local_systemd_observation", unit)
        elif value["enablement"] == "masked":
            add("DRIFT_REQUIRED_UNIT_MASKED", "drift", "local_systemd_observation", unit)
        elif value["load"] == "error" or value["enablement"] == "bad":
            add("SERVICE_UNKNOWN", evidence="unit_state_inconclusive", target=unit)
        elif value["load"] == "loaded" and value["active"] != "active":
            add("DRIFT_REQUIRED_UNIT_INACTIVE", "drift", "local_systemd_observation", unit)
        elif (services.get("role") == "watchtower_candidate"
              and value["enablement"] != "enabled"):
            add("DRIFT_REQUIRED_UNIT_DISABLED", "drift", "local_systemd_observation", unit)
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
        target = finding.get("target")
        rows.append(f'  {finding["code"]}' +
                    (f' [{target}]' if target else "") +
                    f': {finding["proposed_action"]} ({finding["evidence"]})')
    rows.append("No changes applied. Checkout HEAD is not verified GitHub main; "
                "selected release is not runtime health.")
    return "\n".join(rows)
