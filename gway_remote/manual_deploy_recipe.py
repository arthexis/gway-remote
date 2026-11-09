"""Fixed deployment recipe boundary for the Watchtower broker.

Only immutable SHA, allowlisted repository/node and a preinstalled recipe
can be executed. This module deliberately accepts no command, shell or URL.
"""
from __future__ import annotations

import re
import subprocess
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


def repository_installer_argv(repository, node, sha, *, installed=False):
    """Resolve a fixed, preinstalled repository-owned deployment entrypoint.

    No repository checkout or shell arguments can be provided by the caller.
    The privileged wrapper must separately verify its root-owned policy,
    checked-out immutable revision and receipt before invoking deploy.sh.
    """
    if not installed:
        raise PermissionError("repository installer not installed or attested")
    validate_deployment(repository, node, sha)
    if type(sha) is not str or not _SHA.fullmatch(sha):
        raise ValueError("immutable SHA required")
    try:
        entrypoint = SELF_INSTALLERS[(repository, node)]
    except KeyError:
        raise PermissionError("repository installer not approved") from None
    return [*entrypoint, sha]


def repository_installer_preview(repository, node, sha, *, installed=False):
    argv = repository_installer_argv(repository, node, sha, installed=installed)
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
