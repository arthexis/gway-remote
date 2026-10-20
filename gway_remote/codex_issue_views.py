"""Read-only GitHub-backed agent assignment list for Android Companion."""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .codex_discovery import fetch_issues
from .codex_issues import DispatchLedger, ordered_issues
from .codex_policy import ALLOWED
from .codex_queue import default_db


def list_assignments(*, token=None, ledger_path=None, fetcher=fetch_issues):
    token = os.environ.get("GITHUB_TOKEN", "") if token is None else token
    if not token:
        raise RuntimeError("github_token_unavailable")
    items = []
    with DispatchLedger(ledger_path or default_db().with_suffix(".dispatch.sqlite")) as ledger:
        for repo in sorted(ALLOWED):
            # GitHub is the source of truth: never substitute cached local tasks.
            issues = list(fetcher(repo, token))
            labels_by_number = {issue.get("number"): issue.get("labels", []) for issue in issues\n                                if isinstance(issue, dict)}
            for row in ordered_issues(issues, repo, ledger):
                row["repository"] = repo
                row["labels"] = sorted({label["name"] for label in labels_by_number.get(row["number"], [])
                                        if isinstance(label, dict) and isinstance(label.get("name"), str)})
                # Always return a canonical link, not arbitrary issue-provided URLs.
                row["url"] = f"https://github.com/{repo}/issues/{row['number']}"
                items.append(row)
    return {"agent": socket.gethostname().lower(),
            "issues": sorted(items, key=lambda row: (
        {"P0": 0, "P1": 1, "P2": 2, "P3": 3}[row["priority"]],
        row["repository"], row["number"]))}
