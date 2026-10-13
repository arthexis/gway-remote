"""GitHub-first assignment projection and minimal dispatch bookkeeping.

Issues and their comment counts are authoritative. This module deliberately
does not determine whether an agent succeeded, or execute any assignment.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .codex_policy import ALLOWED, DEFAULT_PRIORITY, PRIORITIES, TRUSTED_CREATOR_ID, verify_issue_creator

SCHEMA = """
CREATE TABLE IF NOT EXISTS dispatches (
 repository TEXT NOT NULL,
 issue INTEGER NOT NULL,
 sent_at TEXT NOT NULL,
 comment_baseline INTEGER NOT NULL CHECK(comment_baseline >= 0),
 PRIMARY KEY(repository, issue)
)
"""


def _count(issue: dict) -> int:
    comments = issue.get("comments")
    if type(comments) is not int or comments < 0:
        raise ValueError("missing or invalid GitHub comment count")
    return comments


def eligible_issue(issue: dict, repository: str) -> bool:
    """Only open, creator-owned, labeled issues in allowed repositories."""
    return (
        repository in ALLOWED
        and issue.get("state") == "open"
        and verify_issue_creator(issue, trusted_id=TRUSTED_CREATOR_ID)
        and type(issue.get("number")) is int
        and issue["number"] > 0
        and any(isinstance(label, dict) and label.get("name") == "local-agent"
                for label in issue.get("labels", ()))
    )


def priority(issue: dict) -> str:
    labels = {label.get("name") for label in issue.get("labels", ())
              if isinstance(label, dict)}
    return next((p for p in PRIORITIES if p in labels or ("priority:" + p) in labels),
                DEFAULT_PRIORITY)


def project(issue: dict, dispatch: dict | None = None) -> dict:
    """Display-only view: never call an execution successful."""
    count = _count(issue)
    state = "closed" if issue.get("state") == "closed" else "queued"
    if state != "closed":
        if dispatch is not None:
            baseline = dispatch["comment_baseline"]
            if type(baseline) is not int or baseline < 0:
                raise ValueError("invalid dispatch baseline")
            state = "attended" if count > baseline else "sent"
        elif count:
            state = "attended"
    return {
        "number": issue["number"],
        "title": issue.get("title", ""),
        "url": issue.get("html_url", ""),
        "state": state,
        "comments": count,
        "priority": priority(issue),
        "sent_at": dispatch["sent_at"] if dispatch and state == "sent" else None,
    }


class DispatchLedger:
    """Safety bookkeeping only, not a second GitHub task-state machine."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def get(self, repository: str, number: int) -> dict | None:
        row = self.db.execute(
            "SELECT sent_at,comment_baseline FROM dispatches WHERE repository=? AND issue=?",
            (repository, number)).fetchone()
        return dict(row) if row else None

    def accept(self, repository: str, issue: dict, *, resend: bool = False,
               admitted: bool = False) -> dict:
        """Record only an admitted dispatch; resends always require explicit intent."""
        if not admitted:
            raise ValueError("budget/priority admission not granted")
        if not eligible_issue(issue, repository):
            raise ValueError("issue is not eligible")
        count = _count(issue)
        number = issue["number"]
        current = self.get(repository, number)
        if current is not None and not resend:
            raise ValueError("already sent; explicit resend required")
        sent_at = datetime.now(timezone.utc).isoformat()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                """INSERT INTO dispatches(repository,issue,sent_at,comment_baseline)
                   VALUES (?,?,?,?)
                   ON CONFLICT(repository,issue) DO UPDATE SET
                   sent_at=excluded.sent_at,comment_baseline=excluded.comment_baseline""",
                (repository, number, sent_at, count))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return self.get(repository, number)


def ordered_issues(issues: list[dict], repository: str,
                   ledger: DispatchLedger) -> list[dict]:
    """Return eligible open issues without making a local claim of completion."""
    rows = [project(issue, ledger.get(repository, issue["number"]))
            for issue in issues if eligible_issue(issue, repository)]
    return sorted(rows, key=lambda row: (
        PRIORITIES.index(row["priority"]), row["number"]))
