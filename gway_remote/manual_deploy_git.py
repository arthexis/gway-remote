"""Safe, bounded Git revision resolution for the manual deployment broker.

Only the allowlisted repository is accepted. No shell, user-supplied URL,
branch name or arbitrary Git option can reach the resolver.
"""
from __future__ import annotations

import re
import subprocess

from .manual_deploy_policy import validate_deployment

SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY_URLS = {
    "arthexis/ocpp-reports": "https://github.com/arthexis/ocpp-reports.git",
}


def resolve_sha(repository, revision, *, run=subprocess.run):
    # Validate against the same explicit policy; this is a second independent
    # boundary and never constructs a URL from caller input.
    if repository not in REPOSITORY_URLS:
        raise PermissionError("repository not approved")
    if type(revision) is not str or (revision != "main" and not SHA.fullmatch(revision)):
        raise ValueError("revision must be main or immutable SHA")
    if revision != "main":
        return revision
    completed = run(
        ["git", "ls-remote", "--exit-code", REPOSITORY_URLS[repository], "refs/heads/main"],
        capture_output=True, text=True, timeout=15, check=True,
        env={"PATH": "/usr/bin:/bin", "GIT_TERMINAL_PROMPT": "0",
             "GIT_CONFIG_NOSYSTEM": "1"},
    )
    rows = completed.stdout.splitlines()
    if len(rows) != 1:
        raise ValueError("ambiguous main revision")
    parts = rows[0].split()
    if len(parts) != 2 or parts[1] != "refs/heads/main" or not SHA.fullmatch(parts[0]):
        raise ValueError("invalid remote main revision")
    return parts[0]
