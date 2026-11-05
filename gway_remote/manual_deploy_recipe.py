"""Fixed deployment recipe boundary for the Watchtower broker.

Only immutable SHA, allowlisted repository/node and a preinstalled recipe
can be executed. This module deliberately accepts no command, shell or URL.
"""
from __future__ import annotations

import re
import subprocess

from .manual_deploy_policy import validate_deployment

_SHA = re.compile(r"[0-9a-f]{40}\Z")
# Recipes must be installed root-owned by Ansible; caller cannot choose a path.
RECIPES = {
    ("arthexis/ocpp-reports", "gway-001"): (
        "/usr/local/libexec/gway-deploy-ocpp-reports-gway-001",),
    ("arthexis/ocpp-reports", "ocpp-abb-1"): (
        "/usr/local/libexec/gway-deploy-ocpp-reports-ocpp-abb-1",),
}


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
