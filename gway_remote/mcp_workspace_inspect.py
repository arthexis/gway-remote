"""Read-only workspace inspection through already installed node-owned records.

No MCP caller-supplied paths, hostname environment variables, additional
credentials, workspace allowlist or filesystem crawl. Unregistered/inaccessible
checkouts return explicit unknown evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import stat
import subprocess
import time
from datetime import datetime, timezone

from .mcp_installed_providers import discover_installed_providers
from .mcp_deployment_contract import validate_deployment
from .workspace_inspect import SCHEMA, inspect_workspace

REGISTRY = Path("/etc/gway-mcp-providers")
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_ORIGIN = re.compile(
    r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*?)(?:\.git)?/?\Z"
)


class WorkspaceUnavailable(PermissionError):
    """Sanitized, stable read-only inspection failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _registered_file(path, *, uid):
    """Read only exact root/operator-provisioned policy files, never symlinks."""
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid
            or info.st_mode & 0o022 or info.st_size > 8192):
        raise WorkspaceUnavailable("workspace_registry_invalid")
    return path.read_text(encoding="utf-8")


def _agentops_checkout(repository, *, directory, uid):
    """Existing AgentOps registry names repos and owns its workspace root."""
    if directory.is_symlink():
        raise WorkspaceUnavailable("workspace_registry_invalid")
    info = directory.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
            or info.st_mode & 0o022):
        raise WorkspaceUnavailable("workspace_registry_invalid")
    repo_policy = directory / "agentops.repositories"
    runtime_policy = directory / "agentops.runtime.json"
    if not repo_policy.exists() and not repo_policy.is_symlink():
        return None
    approved = _registered_file(repo_policy, uid=uid).strip().split(",")
    if not approved or any(not _REPOSITORY.fullmatch(item) for item in approved):
        raise WorkspaceUnavailable("workspace_registry_invalid")
    if repository not in approved:
        return None
    runtime = json.loads(_registered_file(runtime_policy, uid=uid))
    if type(runtime) is not dict or type(runtime.get("workspace")) is not str:
        raise WorkspaceUnavailable("workspace_registry_invalid")
    base = Path(runtime["workspace"])
    if not base.is_absolute() or ".." in base.parts:
        raise WorkspaceUnavailable("workspace_registry_invalid")
    # Repository is exactly two validated components. Never list other workspaces.
    return base.joinpath(*repository.split("/"))


def _safe_checkout(path):
    """Reject path traversal, symlinks and writable checkout roots."""
    if not path.is_absolute() or ".." in path.parts:
        return False
    try:
        for part in (path, *path.parents):
            if part.is_symlink():
                return False
        info = path.stat()
        dotgit = path / ".git"
        git_info = dotgit.lstat()
        return (stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o022
                and stat.S_ISDIR(git_info.st_mode) and not dotgit.is_symlink())
    except OSError:
        return False


def _git_origin(path, repository, *, deadline):
    """Reject a Git root outside the declared checkout before reading metadata."""
    env = {"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_COUNT": "0",
           "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    prefix = ["git", "-C", str(path), "-c", "core.fsmonitor=false"]
    for argv, expected_root in (
        (["rev-parse", "--show-toplevel"], True),
        (["config", "--local", "--get", "remote.origin.url"], False),
    ):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WorkspaceUnavailable("workspace_inspection_budget_exceeded")
        try:
            result = subprocess.run(
                [*prefix, *argv], check=False, capture_output=True, text=True,
                timeout=min(1.0, remaining), env=env)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode or len(result.stdout) > 512:
            return False
        value = result.stdout.strip()
        if expected_root:
            # A local core.worktree override could otherwise make 'git status'
            # inspect an unrelated filesystem path.
            if Path(value) != path:
                return False
        else:
            match = _ORIGIN.fullmatch(value)
            return match is not None and match.group(1).lower() == repository.lower()
    return False


_FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


def _existing_installation_receipt(repository):
    """Reuse only independently observed active release links for managed targets.

    The legacy deployers clone temporary Git trees, so the installed revision
    is never evidence of a persistent checkout or of git status. Kiosk revision
    files and Bastion staged releases require separate activation checks.
    """
    from .reconcile import TARGETS
    from .status import installed_revision
    from .deployment_evidence import adapt_component

    matches = [name for name, source in TARGETS if source == repository]
    if len(matches) != 1 or matches[0] in {"gway-ap-kiosk", "gway-bastion"}:
        return None
    try:
        revision = installed_revision(matches[0])
    except (OSError, ValueError, TypeError, RuntimeError):
        return None
    if type(revision) is not str or not _FULL_SHA.fullmatch(revision):
        # 12-character appliance pointers are not a verified full source SHA.
        return None
    return adapt_component({"name": matches[0], "installed_sha": revision,
                            "health": "unknown"}, observed_at=None, depth="quick")


def _unknown(repository, node, reason, *, receipt=None):
    """Git may be unknown independently of a verified installed release."""
    from .workspace_inspect import deployment_evidence
    missing = {"state": "unknown", "reason": reason, "value": None}
    return {
        "schema": SCHEMA, "checked_at": datetime.now(timezone.utc).isoformat(),
        "repository": repository, "node": node,
        "git": {"head": dict(missing), "branch": dict(missing),
                "clean_tracked": dict(missing)},
        "ci": {"state": "unknown", "reason": "GitHub evidence not supplied"},
        "deployment": deployment_evidence(repository, receipt),
    }


def inspect_authorized(arguments: dict, *, trusted_node: str,
                       deployment_receipt: dict | None = None,
                       discover=discover_installed_providers,
                       registry=REGISTRY, trusted_uid=0) -> dict:
    if type(arguments) is not dict or set(arguments) != {"node", "repository"}:
        raise ValueError("invalid workspace inspection arguments")
    node, repository = arguments["node"], arguments["repository"]
    # The trusted node identity is supplied by the forced protocol, not MCP.
    if (type(trusted_node) is not str or not trusted_node
            or node != trusted_node):
        raise WorkspaceUnavailable("node_binding_mismatch")
    if type(repository) is not str or not _REPOSITORY.fullmatch(repository):
        raise ValueError("invalid repository")

    # Installation evidence is independent of whether an ephemeral Git checkout
    # survived the legacy appliance installer.
    receipt = (deployment_receipt if deployment_receipt is not None
               else _existing_installation_receipt(repository))

    try:
        candidates = []
        for provider in discover():
            if not provider.enabled or provider.deployment is None:
                continue
            checkout = validate_deployment(provider.deployment)["checkout"]
            candidates.append(Path(checkout))
        candidate = _agentops_checkout(repository, directory=Path(registry),
                                       uid=trusted_uid)
        if candidate is not None:
            candidates.append(candidate)
        # Only paths supplied by already installed records are ever consulted.
        checked = set()
        matches = []
        # The pinned SSH hop has a 15-second deadline. Bound aggregate local
        # Git metadata checks rather than allowing up to 32 provider timeouts.
        deadline = time.monotonic() + 6.0
        for path in candidates:
            if time.monotonic() >= deadline:
                return _unknown(repository, node, "workspace_inspection_budget_exceeded", receipt=receipt)
            if path in checked:
                continue
            checked.add(path)
            if _safe_checkout(path) and _git_origin(path, repository, deadline=deadline):
                matches.append(path)
        if len(matches) != 1:
            reason = ("ambiguous_registered_checkout" if matches else
                      "registered_workspace_unavailable" if candidate is not None
                      else "repository_not_registered")
            return _unknown(repository, node, reason, receipt=receipt)
        return inspect_workspace(repository, {repository: str(matches[0])},
                                 node=node, deployment_receipt=receipt)
    except WorkspaceUnavailable as exc:
        return _unknown(repository, node, exc.code, receipt=receipt)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return _unknown(repository, node, "workspace_registry_unavailable", receipt=receipt)
