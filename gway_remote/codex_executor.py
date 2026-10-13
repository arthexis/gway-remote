"""Execute an operator-approved issue with the existing Codex CLI configuration."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import signal
import time
import threading
import urllib.request
from typing import Callable

from .codex_queue import TaskQueue, default_db
from .codex_results import reconcile
from .codex_reporting import assignment_prompt, diagnostic_body, ReportOutbox
from .codex_issues import DispatchLedger, eligible_issue
from .codex_policy import TRUSTED_CREATOR_ID, verify_issue_creator

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def issue_objective(task: dict, token: str, *, on_issue=None) -> str:
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
    if not verify_issue_creator(issue, trusted_id=TRUSTED_CREATOR_ID):
        raise ValueError("issue author is not trusted")
    if on_issue is not None:
        on_issue(issue)
    return assignment_prompt(repository, int(task["issue"]),
                             issue.get("title", ""), issue.get("body", ""))


def run_once(*, db: Path | None = None, token: str | None = None,
             repos_root: Path | None = None, work_root: Path | None = None,
             on_claim: Callable[[str], None] | None = None,
             stop: threading.Event | None = None,
             timeout_seconds: int | None = None) -> dict | None:
    """Claim one task and run Codex synchronously; never retry interrupted work."""
    token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
    repos_root = repos_root or Path(os.environ.get("GWAY_CODEX_REPOS_ROOT", str(Path.home() / "Repos")))
    work_root = work_root or Path.home() / ".local/state/gway-remote/codex-worktrees"
    timeout_seconds = (int(os.environ.get("GWAY_CODEX_TIMEOUT_SECONDS", "3600"))
                       if timeout_seconds is None else timeout_seconds)
    if timeout_seconds < 1:
        raise ValueError("Codex timeout must be positive")
    with TaskQueue(db or default_db()) as queue:
        task = queue.claim_next()
        if task is None:
            return None
        task_id = task["id"]
        queue.start_execution(task_id)
        exit_code = None
        output = final = workspace = None
        try:
            if on_claim is not None:
                on_claim(task_id)
            if not token:
                raise RuntimeError("GitHub token unavailable")
            def mark_dispatch(issue):
                # Admission happened in the existing approved queue. An
                # operator may explicitly approve this same issue again.
                if eligible_issue(issue, task["repository"]):
                    with DispatchLedger((db or default_db()).with_suffix(".dispatch.sqlite")) as ledger:
                        ledger.accept(task["repository"], issue, admitted=True, resend=True)
            objective = issue_objective(task, token, on_issue=mark_dispatch)
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
            queue.db.execute(
                "UPDATE task_executions SET workspace_path=?, transcript_path=?, "
                "final_message_path=? WHERE task_id=?",
                (str(workspace), str(output), str(final), task_id),
            )
            with output.open("w", encoding="utf-8") as stream:
                process = subprocess.Popen(
                    ["codex", "exec", "--cd", str(workspace), "--json",
                     "--output-last-message", str(final), objective],
                    stdout=stream, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, start_new_session=True,
                )
                deadline = time.monotonic() + timeout_seconds
                reason = None
                while process.poll() is None:
                    if stop is not None and stop.is_set():
                        reason = "cancelled"
                        break
                    if time.monotonic() >= deadline:
                        reason = "timeout"
                        break
                    time.sleep(0.2)
                if reason:
                    # A child may exit between poll() and killpg(); that is not
                    # an executor failure. Always reap the direct child.
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
                else:
                    process.wait()
            exit_code = process.returncode
            detail = f"exit={process.returncode}; transcript={output}; final={final}; workspace={workspace}"
            if reason == "cancelled":
                state = "interrupted"
                detail += "; worker stopped"
            elif reason == "timeout":
                state = "failed"
                detail += "; timed out"
            else:
                state = "succeeded" if process.returncode == 0 else "failed"
        except Exception as exc:
            state = "failed"
            detail = f"{type(exc).__name__}: {str(exc)[:400]}"
        if state != "succeeded":
            try:
                reason = ("interrupted" if state == "interrupted" else
                          "timeout" if "timed out" in detail else "crash")
                diagnostic = diagnostic_body(reason=reason, exit_code=exit_code,
                                             phase="executing" if output else "preparing")
                with ReportOutbox((db or default_db()).with_suffix(".reports.sqlite")) as outbox:
                    outbox.enqueue(task["repository"], int(task["issue"]), diagnostic,
                                   report_key=task_id)
                    outbox.deliver(token)
            except Exception:
                # Reporting must never mask the original execution outcome.
                pass
        reconciliation = reconcile(final, output, workspace, state)
        return queue.finish_execution(task_id, state, detail, exit_code=exit_code,
                                      reconciliation=reconciliation)
