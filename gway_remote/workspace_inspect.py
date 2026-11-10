"""Read-only workspace inspection, with optional authoritative evidence adapters."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone

SCHEMA = "gway-remote/workspace-inspect/v1"
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


def _unknown(reason: str) -> dict:
    return {"state": "unknown", "reason": reason}


def _run_git(root: Path, *args: str) -> dict:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "-c", "core.fsmonitor=false",
             "-c", "core.hooksPath=/dev/null",
             "-c", "core.worktree=" + str(root), *args],
            capture_output=True, text=True, timeout=2, check=False,
            env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_COUNT": "0",
                 "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"state": "unknown", "value": None}
    if result.returncode:
        return {"state": "unknown", "value": None}
    return {"state": "observed", "value": result.stdout.strip()[:4096]}


def github_evidence(repository: str, client) -> dict:
    """Reuse the existing GitHub adapter and its exact-PR-head CI policy."""
    if client is None:
        return _unknown("GitHub adapter not configured")
    from .github_state import main_head, ci_for_head
    try:
        sha = main_head(client, repository)
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            return _unknown("invalid main revision")
        ci = ci_for_head(client, repository, sha)
        if ci not in ("success", "failure", "pending", "unknown"):
            return _unknown("invalid CI result")
        return {"state": "observed" if ci != "unknown" else "unknown",
                "source": "github_actions", "main_sha": sha, "status": ci}
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return _unknown("GitHub evidence unavailable")


def deployment_evidence(repository: str, evidence: dict | None) -> dict:
    """Consume an existing verified deployment receipt, never infer from a revision file."""
    if evidence is None:
        return _unknown("deployment evidence not supplied")
    if not isinstance(evidence, dict) or evidence.get("repository") != repository:
        return _unknown("deployment evidence repository mismatch")
    sha = evidence.get("activated_revision")
    if (evidence.get("installation_state") != "activated"
            or not isinstance(sha, str) or not _SHA.fullmatch(sha)
            or "verified_active_release" not in evidence.get("evidence", [])):
        return _unknown("no verified active release")
    return {"state": "observed", "source": "deployment_evidence",
            "installed_sha": sha, "runtime_state": evidence.get("runtime_state", "unknown"),
            "observed_at": evidence.get("observed_at")}


def inspect_workspace(
    repository: str, roots: dict[str, str], *, node: str | None = None,
    github_client=None, deployment_receipt: dict | None = None,
) -> dict:
    """Inspect a configured path; external evidence must be explicitly supplied."""
    if repository not in roots:
        raise ValueError("repository is not configured for inspection")
    root = Path(roots[repository]).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("invalid workspace root")
    head = _run_git(root, "rev-parse", "--verify", "HEAD")
    branch = _run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    porcelain = _run_git(root, "status", "--porcelain=v1", "--untracked-files=no")
    clean = {"state": porcelain["state"],
             "value": porcelain["value"] == "" if porcelain["state"] == "observed" else None}
    ci = github_evidence(repository, github_client)
    deployment = deployment_evidence(repository, deployment_receipt)
    if ci.get("main_sha") and deployment.get("installed_sha"):
        deployment["matches_main"] = ci["main_sha"].lower() == deployment["installed_sha"].lower()
    return {
        "schema": SCHEMA,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "repository": repository,
        "node": node,
        "git": {"head": head, "branch": branch, "clean_tracked": clean},
        "ci": ci,
        "deployment": deployment,
    }


def inspect_json(repository: str, roots: dict[str, str], *, node: str | None = None,
                 github_client=None, deployment_receipt: dict | None = None) -> str:
    return json.dumps(inspect_workspace(repository, roots, node=node,
                      github_client=github_client, deployment_receipt=deployment_receipt),
                      sort_keys=True)
