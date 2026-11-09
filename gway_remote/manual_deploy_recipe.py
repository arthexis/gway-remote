"""Fixed deployment recipe boundary for the Watchtower broker.

Only immutable SHA, allowlisted repository/node and a preinstalled recipe
can be executed. This module deliberately accepts no command, shell or URL.
"""
from __future__ import annotations

import re
import subprocess
import json
import os
import stat
from pathlib import Path

from .manual_deploy_policy import validate_deployment

_SHA = re.compile(r"[0-9a-f]{40}\Z")
# Recipes must be installed root-owned by Ansible; caller cannot choose a path.
RECIPES = {
    ("arthexis/ocpp-reports", "gway-001"): (
        "/usr/local/libexec/gway-deploy-ocpp-reports-gway-001",),
    ("arthexis/ocpp-reports", "ocpp-abb-1"): (
        "/usr/local/libexec/gway-deploy-ocpp-reports-ocpp-abb-1",),
}


# A repository-owned installer is selected by a trusted, operator-installed
# registration. It is never a client-provided command or checkout path.
# This pilot is intentionally dormant until a protected registration exists.
SELF_INSTALLERS = {
    ("arthexis/odoo-gelectriic", "gway-001"): (
        "/usr/local/libexec/gway-repository-deploy-odoo-gelectriic",),
}


REGISTRY = Path("/etc/gway-remote/repository-installers.json")


def _trusted_registry(path):
    """Load a small operator-controlled registry; reject writable ancestors."""
    path = Path(path)
    if not path.is_absolute():
        raise PermissionError("registry must be absolute")
    for parent in (path, *path.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError("untrusted registry path")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 8192:
        raise PermissionError("invalid registry file")
    data = json.loads(path.read_text(encoding="utf-8"))
    if type(data) is not dict or set(data) != {"version", "installers"} or data["version"] != 1:
        raise PermissionError("invalid registry schema")
    if type(data["installers"]) is not list or len(data["installers"]) > 32:
        raise PermissionError("invalid registry entries")
    return data["installers"]


def repository_installer_argv(repository, node, sha, *, registry=REGISTRY):
    """Resolve an installed, root-owned wrapper, never a caller-supplied path."""
    validate_deployment(repository, node, sha)
    if type(sha) is not str or not _SHA.fullmatch(sha):
        raise ValueError("immutable SHA required")
    entrypoint = SELF_INSTALLERS.get((repository, node))
    if entrypoint is None:
        raise PermissionError("repository installer not approved")
    matches = [row for row in _trusted_registry(registry)
               if type(row) is dict and row.get("repository") == repository
               and row.get("node") == node]
    if len(matches) != 1 or set(matches[0]) != {"repository", "node", "entrypoint", "enabled"}:
        raise PermissionError("repository installer not registered")
    if matches[0]["enabled"] is not True or matches[0]["entrypoint"] != entrypoint[0]:
        raise PermissionError("repository installer registration mismatch")
    binary = Path(entrypoint[0])
    info = binary.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise PermissionError("untrusted installed wrapper")
    for parent in binary.parents:
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError("untrusted wrapper directory")
    return [*entrypoint, sha]


def repository_installer_preview(repository, node, sha, *, registry=REGISTRY):
    argv = repository_installer_argv(repository, node, sha, registry=registry)
    return {"repository": repository, "node": node, "sha": sha,
            "entrypoint": argv[0], "status": "eligible",
            "execution": "repository-owned-deploy-sh-via-fixed-wrapper"}


def recipe_argv(repository, node, sha):
    validate_deployment(repository, node, sha)
    if type(sha) is not str or not _SHA.fullmatch(sha):
        raise ValueError("immutable SHA required")
    try:
        recipe = RECIPES[(repository, node)]
    except KeyError:
        raise PermissionError("no installed deployment recipe") from None
    return [*recipe, sha]


def execute_recipe(repository, node, sha, *, run=subprocess.run):
    argv = recipe_argv(repository, node, sha)
    # No shell, no user-supplied path or environment, bounded runtime.
    result = run(argv, shell=False, check=False, capture_output=True,
                 text=True, timeout=600, env={"PATH": "/usr/bin:/bin"})
    return {"state": "succeeded" if result.returncode == 0 else "failed",
            "exit_code": result.returncode,
            "output": (result.stdout + result.stderr)[-8192:]}
