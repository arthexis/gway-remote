"""Read-only GitHub Health collector for the Gway-001 appliance.

No workflow dispatches or repository mutations. A failed collection never
publishes a healthy snapshot or resolves historical alerts.
"""
import argparse
import json
import os
import sqlite3
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .github_health import REPOSITORIES
from .github_health_publish import publish
from .github_health_episodes import reconcile
from .github_health_prs import reconcile_prs

API = "https://api.github.com"
CATEGORIES = {"CI_FAILURE_STUCK", "CI_MISSING", "CI_ABNORMALLY_LONG",
              "REVIEW_BLOCKED", "BRANCH_FRESHNESS_BLOCKED",
              "READY_BUT_NOT_MERGING", "STALE_IN_PROGRESS",
              "AUTOMATION_STATE_INCONSISTENCY", "CI_ANOMALY"}


class GitHubReadOnly:
    def __init__(self, token):
        if not token:
            raise ValueError("GITHUB_TOKEN required")
        self.token = token

    def get(self, path):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Invalid API path")
        request = urllib.request.Request(
            API + path, headers={"Authorization": "Bearer " + self.token,
                                 "Accept": "application/vnd.github+json",
                                 "X-GitHub-Api-Version": "2022-11-28",
                                 "User-Agent": "gway-remote-health"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)


def collect(api):
    """Two bounded read-only passes; unknown evidence is never reported healthy."""
    results = []
    findings = []
    for repo in REPOSITORIES:
        encoded = urllib.parse.quote(repo, safe="/")
        pulls = api.get("/repos/" + encoded + "/pulls?state=open&per_page=100")
        runs = api.get("/repos/" + encoded + "/actions/runs?per_page=30")
        if not isinstance(pulls, list) or not isinstance(runs, dict):
            raise ValueError("Unexpected GitHub response for " + repo)
        workflow_runs = runs.get("workflow_runs")
        if not isinstance(workflow_runs, list):
            raise ValueError("Missing workflow runs for " + repo)
        # Pass A: evidence acquisition. Do not classify a PR stuck solely
        # because a check failed or a PR is old: historical persistence and
        # expected automated transitions must first be established.
        for pr in pulls:
            if not isinstance(pr, dict) or "number" not in pr:
                raise ValueError("Incomplete PR evidence")
        # Branch protection identifies required checks; inaccessible protection
        # leaves PR blockers unverified rather than inventing failures.
        required = set()
        try:
            protection = api.get("/repos/" + encoded +
                                 "/branches/main/protection/required_status_checks")
            if isinstance(protection, dict):
                required.update(x for x in protection.get("contexts", []) if isinstance(x, str))
                required.update(x.get("context") for x in protection.get("checks", [])
                                if isinstance(x, dict) and isinstance(x.get("context"), str))
        except urllib.error.HTTPError as exc:
            if exc.code not in (403, 404):
                raise
        pr_evidence = []
        for pr in pulls:
            head = pr.get("head") or {}
            sha = head.get("sha")
            if not isinstance(sha, str) or not sha:
                raise ValueError("Missing PR head SHA")
            checks = api.get("/repos/" + encoded + "/commits/" +
                             urllib.parse.quote(sha, safe="") + "/check-runs?per_page=100")
            if not isinstance(checks, dict) or not isinstance(checks.get("check_runs"), list):
                raise ValueError("Missing head checks")
            head_runs = checks["check_runs"]
            reviews = api.get("/repos/" + encoded + "/pulls/" + str(pr["number"]) +
                              "/reviews?per_page=100")
            if not isinstance(reviews, list):
                raise ValueError("Missing PR review evidence")
            latest_reviews = {}
            for review in reviews:
                user = review.get("user") or {}
                if user.get("login") and review.get("state") in (
                        "APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
                    latest_reviews[user["login"]] = review["state"]
            review_blocked = "CHANGES_REQUESTED" in latest_reviews.values()
            age_seconds = None
            if pr.get("updated_at"):
                try:
                    age_seconds = (datetime.now(timezone.utc) -
                        datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00"))).total_seconds()
                except ValueError:
                    pass
            failing = any(c.get("status") == "completed" and
                          c.get("conclusion") in ("failure", "timed_out", "action_required")
                          for c in head_runs)
            required_failed = any(c.get("name") in required and
                                  c.get("status") == "completed" and
                                  c.get("conclusion") in ("failure", "timed_out", "action_required")
                                  for c in head_runs)
            pending = any(c.get("status") != "completed" for c in head_runs)
            labels = {label.get("name") for label in pr.get("labels", [])
                      if isinstance(label, dict)}
            pr_evidence.append({
                "number": pr["number"], "head_sha": sha,
                "url": pr.get("html_url") or "",
                "draft": pr.get("draft") is True,
                "on_hold": "on-hold" in labels,
                "head_check": "pending" if pending else "failure" if failing else "other",
                # GitHub check-runs alone do not establish branch-protection
                # requirements. Never claim a required-check blocker yet.
                "required_check_verified": required_failed,
                "review_blocked": review_blocked,
                "mergeable_state": pr.get("mergeable_state") or "unknown",
                "age_seconds": age_seconds,
                "required_check_count": len(required),
                "check_count": len(head_runs),
                "checks_pending": pending,
                "checks_failing": failing,
                "missing_required_checks": sorted(required - {
                    c.get("name") for c in head_runs if isinstance(c.get("name"), str)}),
                "auto_merge_enabled": bool(pr.get("auto_merge")),
                "updated_at": pr.get("updated_at"),
            })
        # Pass B: retain failed-run evidence, but never infer root cause from
        # a single failure, nor compare non-equivalent lanes.
        for run in workflow_runs:
            if not isinstance(run, dict) or "id" not in run:
                raise ValueError("Incomplete CI evidence")
            if run.get("status") == "completed" and run.get("conclusion") in (
                    "failure", "timed_out", "action_required"):
                findings.append({
                    "repository": repo, "workflow": run.get("name"),
                    "run_id": run["id"], "conclusion": run["conclusion"],
                    "url": run.get("html_url")})
        lanes = {}
        for run in workflow_runs:
            if run.get("status") != "completed" or run.get("conclusion") is None:
                continue
            workflow, trigger, branch = run.get("name"), run.get("event"), run.get("head_branch")
            if not all(isinstance(v, str) and v for v in (workflow, trigger, branch)):
                continue
            lanes.setdefault((workflow, trigger, branch), []).append({
                "id": run["id"], "conclusion": run["conclusion"],
                "url": run.get("html_url") or "",
                "created_at": run.get("created_at") or ""})
        ci_lanes = []
        for (workflow, trigger, branch), lane_runs in lanes.items():
            lane_runs.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
            ci_lanes.append({"workflow": workflow, "trigger": trigger,
                             "branch": branch, "completed_runs": lane_runs})
        results.append({
            "name": repo, "pass_a_checked": True, "pass_b_checked": True,
            "open_pr_count": len(pulls), "recent_run_count": len(workflow_runs),
            "ci_lanes": ci_lanes, "pr_evidence": pr_evidence,
            "recent_failed_runs": [f for f in findings if f["repository"] == repo],
        })
    return results


def store_observation(db_path, completed_at, repositories):
    """SQLite is authoritative for observations; no fabricated alert clearances."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS observations ("
            "completed_at TEXT NOT NULL, repository TEXT NOT NULL, "
            "payload TEXT NOT NULL, PRIMARY KEY(completed_at, repository))")
        for repo in repositories:
            connection.execute(
                "INSERT INTO observations VALUES (?, ?, ?)",
                (completed_at, repo["name"], json.dumps(repo, sort_keys=True)))
        alerts = reconcile(connection, repositories, completed_at)
        alerts.extend(reconcile_prs(connection, repositories, completed_at))
        return alerts


def check(api, db_path, snapshot_path):
    repositories = collect(api)
    completed_at = datetime.now(timezone.utc).isoformat()
    alerts = store_observation(db_path, completed_at, repositories)
    # Alert classification remains intentionally conservative: evidence-only
    # observations do not count as active or resolved alert episodes.
    snapshot = {"schema_version": 1, "status": "available",
                "completed_at": completed_at, "repositories": repositories,
                "alerts": alerts, "classification_status": "partial_verified_checks"}
    destination = Path(snapshot_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                         dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(snapshot, stream)
        publish(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only appliance GitHub health check")
    parser.add_argument("--db", default=os.environ.get("GWAY_REMOTE_GITHUB_HEALTH_DB",
                        "~/.local/state/gway-remote/github-health.sqlite3"))
    parser.add_argument("--snapshot", default=os.environ.get(
        "GWAY_REMOTE_GITHUB_HEALTH_SNAPSHOT",
        "~/.local/state/gway-remote/github-health.json"))
    args = parser.parse_args(argv)
    check(GitHubReadOnly(os.environ.get("GITHUB_TOKEN")),
          Path(args.db).expanduser(), Path(args.snapshot).expanduser())


if __name__ == "__main__":
    main()
