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
 delivered_at TEXT,
 report_key TEXT UNIQUE
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
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(pending_reports)")}
        if "report_key" not in columns:
            self.db.execute("ALTER TABLE pending_reports ADD COLUMN report_key TEXT")
        if self.path != Path(":memory:"):
            self.path.chmod(0o600)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def enqueue(self, repository: str, issue: int, body: str, *, report_key: str | None = None) -> int:
        if not repository or type(issue) is not int or issue < 1 or not body:
            raise ValueError("invalid diagnostic")
        self.db.execute(
            "INSERT OR IGNORE INTO pending_reports(repository,issue,body,created_at,report_key) VALUES (?,?,?,?,?)",
            (repository, issue, body, datetime.now(timezone.utc).isoformat(), report_key))
        row = self.db.execute("SELECT id FROM pending_reports WHERE report_key=?", (report_key,)).fetchone() if report_key else None
        return row["id"] if row else self.db.execute("SELECT last_insert_rowid()").fetchone()[0]

    def pending(self) -> list[dict]:
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM pending_reports WHERE delivered_at IS NULL ORDER BY id")]

    def deliver(self, token: str, *, opener=urlopen) -> int:
        """Retry undelivered reports; preserve the outbox on all HTTP failures."""
        if not token:
            return 0
        sent = 0
        for row in self.pending():
            # A stable marker makes delivery recoverable after POST succeeds but
            # before the local acknowledgement is committed.
            marker = f"<!-- gway-remote-report:{row['report_key']} -->" if row["report_key"] else ""
            if marker:
                try:
                    found = False
                    # Scan all pages; checking only the newest 100 would
                    # duplicate a report on heavily discussed issues.
                    for page in range(1, 101):
                        check_url = (f"https://api.github.com/repos/{row['repository']}/issues/"
                                     f"{row['issue']}/comments?per_page=100&page={page}")
                        check = Request(check_url, headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/vnd.github+json",
                            "User-Agent": "gway-remote-codex-worker"})
                        with opener(check, timeout=20) as response:
                            existing = json.load(response)
                        if not isinstance(existing, list):
                            raise ValueError("invalid GitHub comment listing")
                        if any(isinstance(item, dict) and marker in item.get("body", "")
                               for item in existing):
                            found = True
                            break
                        if len(existing) < 100:
                            break
                    else:
                        # Do not POST if duplicate detection was incomplete.
                        break
                    if found:
                        self.db.execute("UPDATE pending_reports SET delivered_at=? WHERE id=?",
                                        (datetime.now(timezone.utc).isoformat(), row["id"]))
                        sent += 1
                        continue
                except (OSError, ValueError, TypeError):
                    break
            url = f"https://api.github.com/repos/{row['repository']}/issues/{row['issue']}/comments"
            request = Request(url, data=json.dumps({"body": row["body"] + ("\\n\\n" + marker if marker else "")}).encode(),
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
