"""Issue-first assignment instructions and best-effort durable failure reporting.

GitHub issue comments are the review surface; no result classifier is used.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

MAX_DETAIL = 600
SCHEMA = """CREATE TABLE IF NOT EXISTS pending_reports (
 id INTEGER PRIMARY KEY,
 repository TEXT NOT NULL,
 issue INTEGER NOT NULL,
 body TEXT NOT NULL,
 created_at TEXT NOT NULL,
 delivered_at TEXT
)"""


def assignment_prompt(repository: str, issue: int, title: str, body: str) -> str:
    """Give the agent one issue to work on and explicitly forbid closing it."""
    url = f"https://github.com/{repository}/issues/{issue}"
    return (
        f"Assignment: {repository}#{issue}\nIssue URL: {url}\n\n"
        "Read the issue and relevant repository instructions. Follow its acceptance "
        "criteria within your authorized scope.\n"
        "Post a comment on THIS GitHub issue explaining work performed, tests, "
        "blockers, and relevant artifacts. Do not close the issue; its original "
        "creator reviews and closes it. Do not merge or deploy.\n\n"
        f"Issue title: {title}\nIssue body:\n{body[:25000]}"
    )


def diagnostic_body(*, reason: str, detail: str = "", exit_code: int | None = None,
                    elapsed_seconds: float | None = None, phase: str = "unknown") -> str:
    """Sanitized, bounded summary only; never include arbitrary transcript contents."""
    if reason not in ("crash", "timeout", "cancelled", "interrupted", "setup_failure"):
        raise ValueError("invalid failure reason")
    if phase not in ("unknown", "preparing", "executing", "reporting"):
        raise ValueError("invalid execution phase")
    lines = ["Agent execution ended without a confirmed issue response.",
             f"Reason: {reason}", f"Last phase: {phase}"]
    if exit_code is not None:
        lines.append(f"Exit code: {int(exit_code)}")
    if elapsed_seconds is not None:
        lines.append(f"Elapsed: {max(0, int(elapsed_seconds))}s")
    # Detail is caller-supplied metadata, never raw logs or exception messages.
    if detail:
        lines.append(f"Diagnostic: {detail[:MAX_DETAIL]}")
    lines.append("Assignment remains open for the creator to review. No automatic retry.")
    return "\n".join(lines)


class ReportOutbox:
    """Persist crash diagnostics before attempting a GitHub comment."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def enqueue(self, repository: str, issue: int, body: str) -> int:
        if not repository or type(issue) is not int or issue < 1 or not body:
            raise ValueError("invalid diagnostic")
        cursor = self.db.execute(
            "INSERT INTO pending_reports(repository,issue,body,created_at) VALUES (?,?,?,?)",
            (repository, issue, body, datetime.now(timezone.utc).isoformat()))
        return cursor.lastrowid

    def pending(self) -> list[dict]:
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM pending_reports WHERE delivered_at IS NULL ORDER BY id")]

    def deliver(self, token: str, *, opener=urlopen) -> int:
        """Retry undelivered reports; preserve the outbox on all HTTP failures."""
        if not token:
            return 0
        sent = 0
        for row in self.pending():
            url = f"https://api.github.com/repos/{row['repository']}/issues/{row['issue']}/comments"
            request = Request(url, data=json.dumps({"body": row["body"]}).encode(),
                              headers={"Authorization": f"Bearer {token}",
                                       "Accept": "application/vnd.github+json",
                                       "Content-Type": "application/json",
                                       "User-Agent": "gway-remote-codex-worker"},
                              method="POST")
            try:
                with opener(request, timeout=20) as response:
                    reply = json.load(response)
                if not isinstance(reply, dict) or not isinstance(reply.get("id"), int):
                    break
            except (OSError, ValueError, TypeError):
                break
            self.db.execute("UPDATE pending_reports SET delivered_at=? WHERE id=?",
                            (datetime.now(timezone.utc).isoformat(), row["id"]))
            sent += 1
        return sent
