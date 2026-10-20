"""Read-only GitHub adapter for appliance reconciliation.

Requires a token with read access to participating repositories and Actions.
Never writes deployment records; missing state fails closed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from urllib.request import Request, urlopen

from .reconcile import TARGETS
from .attempt_policy import Candidate, plan


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GitHub:
    def __init__(self, token: str | None = None):
        self.token = token if token is not None else os.getenv("GH_TOKEN", os.getenv("GITHUB_TOKEN", ""))

    def get(self, path: str):
        request = Request(
            "https://api.github.com/" + path.lstrip("/"),
            headers={"Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     **({"Authorization": "Bearer " + self.token} if self.token else {})},
        )
        with urlopen(request, timeout=20) as response:
            return json.load(response)



def main_head(client: GitHub, repository: str):
    return client.get(f"repos/{repository}/branches/main")["commit"]["sha"]


def main_arrival(client: GitHub, repository: str, sha: str):
    """Use the main HEAD commit timestamp, independent of Actions history.

    Squash/merge commits on main carry a committer timestamp. A direct push
    may have an older timestamp, but still requires successful main CI.
    """
    data = client.get(f"repos/{repository}/commits/{sha}")
    commit = data.get("commit") or {}
    date = (commit.get("committer") or {}).get("date")
    return timestamp(date) if date else None


def ci_for_head(client: GitHub, repository: str, sha: str):
    """Verify successful PR CI of the exact PR merged to this main commit.

    No push CI is required. Fail closed if the merge/PR provenance or CI
    result is unavailable or ambiguous.
    """
    pulls = client.get(f"repos/{repository}/commits/{sha}/pulls")
    if not isinstance(pulls, list):
        return "unknown"
    matches = [pr for pr in pulls
               if pr.get("merged_at")
               and (pr.get("merge_commit_sha") or "").lower() == sha.lower()
               and (pr.get("base") or {}).get("ref") == "main"
               and (pr.get("base") or {}).get("repo", {}).get("full_name") == repository
               and (pr.get("head") or {}).get("repo", {}).get("full_name") == repository]
    if len(matches) != 1:
        return "unknown"
    pr = matches[0]
    head_sha = (pr.get("head") or {}).get("sha") or ""
    number = pr.get("number")
    if len(head_sha) != 40 or not all(c in "0123456789abcdefABCDEF" for c in head_sha) or type(number) is not int:
        return "unknown"
    data = client.get(
        f"repos/{repository}/actions/runs?event=pull_request&head_sha={head_sha}&per_page=100")
    runs = [r for r in data.get("workflow_runs", [])
            if r.get("event") == "pull_request"
            and r.get("head_sha", "").lower() == head_sha.lower()
            and (not r.get("pull_requests") or any(p.get("number") == number for p in r.get("pull_requests", [])))]
    if not runs:
        return "unknown"
    if any(r.get("status") != "completed" for r in runs):
        return "pending"
    return "success" if all(r.get("conclusion") == "success" for r in runs) else "failure"


def collect(client, attempts=None):
    attempts = attempts or {}
    states = []
    for name, repository in TARGETS:
        sha = main_head(client, repository)
        states.append(Candidate(name, sha, main_arrival(client, repository, sha),
                                ci_for_head(client, repository, sha), attempts.get(name)))
    return tuple(states)


def report(client, now=None, attempts=None):
    states = collect(client, attempts)
    result = plan(states, now or datetime.now(timezone.utc))
    return {"decision": result.state, "reason": result.reason,
            "targets": [{"name": s.name, "desired": s.sha,
                         "last_attempted": s.attempted_sha, "ci": s.ci}
                        for s in states],
            "attempt": [{"name": name, "sha": sha} for name, sha in result.pending]}
