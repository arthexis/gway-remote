"""Opt-in one-shot GitHub discovery. No background polling or execution."""
from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .codex_policy import ALLOWED, TRUSTED_CREATOR_ID, verify_issue_creator

DEFAULT_KIND = "field-validation"


def fetch_issues(repository: str, token: str, *, opener=urlopen):
    """Page through GitHub issues; fail closed on HTTP errors."""
    if repository not in ALLOWED:
        raise ValueError("repository not allowlisted")
    if not token:
        raise ValueError("GITHUB_TOKEN is required for discovery")
    page = 1
    while True:
        url = "https://api.github.com/repos/" + repository + "/issues?" + urlencode(
            {"state": "open", "per_page": 100, "page": page})
        req = Request(url, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gway-remote-codex-discovery",
        })
        with opener(req, timeout=20) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError("unexpected GitHub response")
        yield from batch
        if len(batch) < 100:
            break
        page += 1


def verify_withdrawn(repository: str, issue: int, token: str, *, opener=urlopen):
    """Confirm removal independently; errors are unknown, never withdrawn."""
    req = Request(
        f"https://api.github.com/repos/{repository}/issues/{issue}",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gway-remote-codex-discovery",
        },
    )
    with opener(req, timeout=20) as response:
        data = json.load(response)
    if not isinstance(data, dict) or data.get("number") != issue:
        raise ValueError("unexpected issue verification response")
    if data.get("state") not in ("open", "closed"):
        raise ValueError("unknown issue state")
    labels = data.get("labels")
    if not isinstance(labels, list):
        raise ValueError("missing issue labels")
    return data["state"] == "closed"


def discover(queue, token: str, *, repositories=None, fetcher=fetch_issues, verifier=verify_withdrawn):
    """Reconcile historical imports only; AgentOps owns all automatic pickup.

    The compatibility signature is retained. Do not create or approve a task
    from GitHub labels in this independent legacy queue.
    """
    result = {"imported": 0, "existing": 0, "ignored": 0, "withdrawn": 0}
    for repo in (repositories if repositories is not None else ALLOWED):
        if repo not in ALLOWED:
            raise ValueError("repository not allowlisted")
        rows = queue.db.execute(
            "SELECT id, issue, state FROM tasks WHERE repository=? AND source='github' "
            "AND state IN ('requested','queued')", (repo,)).fetchall()
        for row in rows:
            try:
                closed = verifier(repo, row["issue"], token)
            except Exception:
                continue
            if closed is not True:
                continue
            queue.db.execute("BEGIN IMMEDIATE")
            try:
                updated = queue.db.execute(
                    "UPDATE tasks SET state='cancelled', updated_at=?, detail=? "
                    "WHERE id=? AND state=? AND source='github'",
                    (__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                     "GitHub confirmed issue closed", row["id"], row["state"]),
                )
                result["withdrawn"] += updated.rowcount
                queue.db.execute("COMMIT")
            except Exception:
                queue.db.execute("ROLLBACK")
                raise
    return result
