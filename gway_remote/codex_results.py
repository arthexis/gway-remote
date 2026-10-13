"""Conservative, local-only reconciliation of Codex execution evidence.

The agent's report is a claim, never proof of completed work. Git references
are discovered from the transcript but are not treated as verified GitHub state.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MAX_REPORT = 16000
MAX_TRANSCRIPT = 4 * 1024 * 1024
PR_URL = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/([0-9]+)(?![0-9])")
COMMIT_URL = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/commit/([a-fA-F0-9]{40})(?![a-fA-F0-9])")


def _read(path: Path | None, limit: int) -> str:
    if path is None:
        return ""
    try:
        with Path(path).open("rb") as stream:
            return stream.read(limit + 1)[:limit].decode("utf-8", errors="replace")
    except (OSError, ValueError, TypeError):
        return ""


def reconcile(final: Path | None, transcript: Path | None,
              workspace: Path | None, state: str) -> dict:
    """Return serializable evidence; never infer CI status from agent text."""
    report = _read(final, MAX_REPORT).strip()
    log = _read(transcript, MAX_TRANSCRIPT)
    claimed = "unknown"
    if state in ("failed", "interrupted", "cancelled"):
        claimed = "not_completed"
    elif report:
        # Explicit structured self-report only. Free text cannot certify completion.
        try:
            data = json.loads(report)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict) and data.get("outcome") in (
            "completed", "blocked", "needs_review"
        ):
            claimed = data["outcome"]
    artifacts = []
    seen = set()
    for kind, pattern in (("pull_request", PR_URL), ("commit", COMMIT_URL)):
        for match in pattern.finditer(report + "\n" + log):
            repository, identifier = match.groups()
            url = match.group(0)
            if url not in seen:
                seen.add(url)
                artifacts.append({"kind": kind, "repository": repository,
                                  "id": identifier, "url": url, "verified": False})
            if len(artifacts) >= 50:
                break
    return {
        "report": report,
        "reported_outcome": claimed,
        "verification": "unverified",
        "artifacts_json": json.dumps(artifacts, separators=(",", ":")),
    }
