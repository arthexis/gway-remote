"""Read-only, bounded workspace inspection; no shell, checkout writes or network calls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone


SCHEMA = "gway-remote/workspace-inspect/v1"


def _run_git(root: Path, *args: str) -> dict:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=5, check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"state": "unknown", "value": None}
    if result.returncode:
        return {"state": "unknown", "value": None}
    return {"state": "observed", "value": result.stdout.strip()[:4096]}


def inspect_workspace(repository: str, roots: dict[str, str], *, node: str | None = None) -> dict:
    """Inspect an explicitly configured repository path; callers cannot supply paths."""
    if repository not in roots:
        raise ValueError("repository is not configured for inspection")
    root = Path(roots[repository]).resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("invalid workspace root")
    head = _run_git(root, "rev-parse", "--verify", "HEAD")
    branch = _run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    porcelain = _run_git(root, "status", "--porcelain=v1", "--untracked-files=no")
    clean = {"state": porcelain["state"], "value": porcelain["value"] == "" if porcelain["state"] == "observed" else None}
    return {
        "schema": SCHEMA,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "repository": repository,
        "node": node,
        "git": {"head": head, "branch": branch, "clean_tracked": clean},
        "ci": {"state": "unknown", "reason": "GitHub CI adapter not configured"},
        "deployment": {"state": "unknown", "reason": "deployment evidence adapter not configured"},
    }


def inspect_json(repository: str, roots: dict[str, str], *, node: str | None = None) -> str:
    return json.dumps(inspect_workspace(repository, roots, node=node), sort_keys=True)
