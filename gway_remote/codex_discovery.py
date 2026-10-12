"""Opt-in one-shot GitHub discovery. No background polling or execution."""
from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .codex_policy import ALLOWED, TRUSTED_CREATOR_ID, verify_issue_creator

LABEL = "local-agent"
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
            {"state": "open", "labels": LABEL, "per_page": 100, "page": page})
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
    return data["state"] == "closed" or LABEL not in [
        label.get("name") for label in labels if isinstance(label, dict)
    ]


def discover(queue, token: str, *, repositories=None, fetcher=fetch_issues, verifier=verify_withdrawn):
    """Import only creator-verified labeled issues; never queue or execute."""
    result = {"imported": 0, "existing": 0, "ignored": 0, "withdrawn": 0}
    for repo in (repositories if repositories is not None else ALLOWED):
        if repo not in ALLOWED:
            raise ValueError("repository not allowlisted")
        seen = set()
        for issue in fetcher(repo, token):
            if not verify_issue_creator(issue, trusted_id=TRUSTED_CREATOR_ID):
                result["ignored"] += 1
                continue
            number = issue.get("number")
            if type(number) is not int or number <= 0:
                result["ignored"] += 1
                continue
            seen.add(number)
            # The active-task identity index prevents duplicate imports.
            # Terminal tasks (including vetoes, once added) must also remain
            # permanently discoverable as prior decisions.
            prior = queue.db.execute(
                "SELECT id FROM tasks WHERE repository=? AND issue=? LIMIT 1",
                (repo, number)).fetchone()
            if prior:
                result["existing"] += 1
                continue
            queue.admit(DEFAULT_KIND, repo, number, source="github")
            result["imported"] += 1
        # Only reconcile after a complete successful listing. Never alter
        # manually submitted tasks or currently running work.
        rows = queue.db.execute(
            "SELECT id, issue, state FROM tasks WHERE repository=? AND source='github' "
            "AND state IN ('requested','queued')", (repo,)).fetchall()
        withdrawals = []
        for row in rows:
            if row["issue"] not in seen:
                try:
                    confirmed = verifier(repo, row["issue"], token)
                except Exception:
                    # 403, 404, timeout, malformed payload: preserve local task.
                    continue
                if confirmed:
                    withdrawals.append(row)
        # Apply all confirmed withdrawals atomically. A concurrent change
        # from queued to running is never cancelled.
        queue.db.execute("BEGIN IMMEDIATE")
        try:
            for row in withdrawals:
                updated = queue.db.execute(
                    "UPDATE tasks SET state='cancelled', updated_at=?, detail=? "
                    "WHERE id=? AND state=? AND source='github'",
                    (__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                     "GitHub confirmed issue closed or local-agent label removed",
                     row["id"], row["state"]),
                )
                result["withdrawn"] += updated.rowcount
            queue.db.execute("COMMIT")
        except Exception:
            queue.db.execute("ROLLBACK")
            raise
    return result
