"""Read-only GitHub adapter for appliance reconciliation.

Requires a token with read access to participating repositories and Actions.
Never writes deployment records; missing state fails closed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from urllib.request import Request, urlopen
from urllib.parse import quote

from .reconcile import TARGETS, TargetState, reconcile


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
    """Use the main push workflow run timestamp only when its head SHA matches.

    GitHub Actions may not exist for direct pushes. Missing evidence blocks
    deployment rather than falling back to misleading commit author dates.
    """
    data = client.get(f"repos/{repository}/actions/runs?branch=main&event=push&per_page=50")
    matching = [r for r in data.get("workflow_runs", [])
                if r.get("head_sha", "").lower() == sha.lower()]
    if not matching:
        return None
    return min(timestamp(r["created_at"]) for r in matching)


def ci_for_head(client: GitHub, repository: str, sha: str):
    """Conservative status: all completed push workflow runs for this SHA must pass."""
    data = client.get(f"repos/{repository}/actions/runs?branch=main&event=push&per_page=50")
    runs = [r for r in data.get("workflow_runs", [])
            if r.get("head_sha", "").lower() == sha.lower()]
    if not runs:
        return "unknown"
    if any(r.get("status") != "completed" for r in runs):
        return "pending"
    return "success" if all(r.get("conclusion") == "success" for r in runs) else "failure"


def last_deployed(client: GitHub, repository: str):
    """Last successful deployment for the exact gway-001 environment."""
    data = client.get(f"repos/{repository}/deployments?environment=gway-001&per_page=100")
    for deployment in data:
        statuses = client.get(f"repos/{repository}/deployments/{deployment['id']}/statuses?per_page=100")
        if statuses and statuses[0].get("state") == "success":
            return deployment.get("sha")
    return None


def collect(client: GitHub):
    states = []
    for name, repository in TARGETS:
        sha = main_head(client, repository)
        states.append(TargetState(name, sha, last_deployed(client, repository),
                                  main_arrival(client, repository, sha),
                                  ci_for_head(client, repository, sha)))
    return tuple(states)


def report(client: GitHub, now: datetime | None = None):
    states = collect(client)
    plan = reconcile(states, now or datetime.now(timezone.utc))
    return {
        "decision": plan.decision.value,
        "reason": plan.reason,
        "quiet_until": plan.quiet_until.isoformat() if plan.quiet_until else None,
        "targets": [{"name": s.name, "desired": s.desired_sha,
                     "deployed": s.deployed_sha, "ci": s.ci_status,
                     "main_updated_at": s.main_updated_at.isoformat() if s.main_updated_at else None}
                    for s in states],
        "deploy": [{"name": t.name, "sha": t.sha} for t in plan.targets],
    }
