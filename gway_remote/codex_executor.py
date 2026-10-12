"""Execute an operator-approved issue with the existing Codex CLI configuration."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request
from typing import Callable

from .codex_queue import TaskQueue, default_db

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def issue_objective(task: dict, token: str) -> str:
    repository = task["repository"]
    if not _REPO.fullmatch(repository):
        raise ValueError("invalid repository")
    url = f"https://api.github.com/repos/{repository}/issues/{int(task['issue'])}"
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "gway-remote-codex-worker",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        issue = json.load(response)
    if "pull_request" in issue or issue.get("state") != "open":
        raise ValueError("assignment must refer to an open issue")
    if issue.get("user", {}).get("login", "").lower() != "arthexis":
        raise ValueError("issue author is not trusted")
    return f"Implement approved GitHub assignment {repository}#{task['issue']}:\n" + (
        issue.get("title", "") + "\n\n" + issue.get("body", "")
    )[:30000] + "\n\nDo not merge or deploy. Report tests and results."


def run_once(*, db: Path | None = None, token: str | None = None,
             repos_root: Path | None = None, work_root: Path | None = None,
             on_claim: Callable[[str], None] | None = None) -> dict | None:
    """Claim one task and run Codex synchronously; never retry interrupted work."""
    token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
    repos_root = repos_root or Path(os.environ.get("GWAY_CODEX_REPOS_ROOT", str(Path.home() / "Repos")))
    work_root = work_root or Path.home() / ".local/state/gway-remote/codex-worktrees"
    with TaskQueue(db or default_db()) as queue:
        task = queue.claim_next()
        if task is None:
            return None
        task_id = task["id"]
        try:
            if on_claim is not None:
                on_claim(task_id)
            if not token:
                raise RuntimeError("GitHub token unavailable")
            objective = issue_objective(task, token)
            repository = task["repository"]
            checkout = (repos_root / repository.split("/")[1]).resolve()
            if not checkout.is_dir() or not (checkout / ".git").exists():
                raise RuntimeError("configured repository checkout missing")
            work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            workspace = work_root / task_id
            subprocess.run(["git", "-C", str(checkout), "worktree", "add",
                            "--detach", str(workspace), "HEAD"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            output = work_root / (task_id + ".jsonl")
            final = work_root / (task_id + ".final.txt")
            with output.open("w", encoding="utf-8") as stream:
                result = subprocess.run(
                    ["codex", "exec", "--cd", str(workspace), "--json",
                     "--output-last-message", str(final), objective],
                    stdout=stream, stderr=subprocess.STDOUT, check=False,
                    stdin=subprocess.DEVNULL,
                )
            detail = f"exit={result.returncode}; transcript={output}; final={final}; workspace={workspace}"
            state = "succeeded" if result.returncode == 0 else "failed"
        except Exception as exc:
            state = "failed"
            detail = f"{type(exc).__name__}: {str(exc)[:400]}"
        return queue.transition(task_id, "running", state, detail)
