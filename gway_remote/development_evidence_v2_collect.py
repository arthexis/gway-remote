"""Bounded read-only V2 collection via the existing local and GitHub readers.

No new credentials, tool surface, deployment path, storage or service.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .attempts import read_attempts
from .development_evidence import _sha
from .development_evidence_v2 import development_evidence_v2
from .github_state import main_head
from .reconcile import TARGETS
from .status import status


def _time():
    return datetime.now(timezone.utc).isoformat()


def _verified_pr_ci(client, repository, main_sha):
    """Map exact merged main SHA to exact PR-head Actions run, conservatively.

    The run's real SHA is distinct from a squash merge's main SHA. The
    returned mapped SHA is the *verified applicability to main*, not a claim
    that a PR job executed on the squash commit.
    """
    pulls = client.get(f"repos/{repository}/commits/{main_sha}/pulls")
    if not isinstance(pulls, list) or len(pulls) >= 100:
        return "unknown", None, None
    matches = [p for p in pulls if isinstance(p, dict)
               and p.get("merged_at")
               and p.get("merge_commit_sha") == main_sha
               and (p.get("base") or {}).get("ref") == "main"
               and ((p.get("base") or {}).get("repo") or {}).get("full_name") == repository
               and ((p.get("head") or {}).get("repo") or {}).get("full_name") == repository
               and type(p.get("number")) is int]
    if len(matches) != 1:
        return "unknown", None, None
    pr = matches[0]
    pr_sha = _sha((pr.get("head") or {}).get("sha"))
    if pr_sha is None:
        return "unknown", None, None
    response = client.get(
        f"repos/{repository}/actions/runs?event=pull_request&head_sha={pr_sha}&per_page=100"
    )
    runs = response.get("workflow_runs") if isinstance(response, dict) else None
    if not isinstance(runs, list) or len(runs) >= 100:
        return "unknown", None, pr_sha
    matching = [r for r in runs if isinstance(r, dict)
                and r.get("event") == "pull_request"
                and _sha(r.get("head_sha")) == pr_sha
                and isinstance(r.get("pull_requests"), list)
                and any(isinstance(p, dict) and p.get("number") == pr["number"]
                        for p in r["pull_requests"])
                and type(r.get("id")) is int]
    # Ambiguous/rerun/page-truncated CI cannot be promoted as success.
    if len(matching) != 1:
        return "unknown", None, pr_sha
    run = matching[0]
    if run.get("status") != "completed":
        return "pending", run["id"], pr_sha
    if run.get("conclusion") != "success":
        return "failure", run["id"], pr_sha
    return "success", run["id"], pr_sha


def collect_v2(name, *, client, journal_reader=read_attempts,
               status_reader=status, clock=_time, max_age_seconds=None):
    """Collect existing read contracts; only the local gway-001 owner may call.

    The injected client is already authorized by existing GitHub read policy.
    All read timestamps are taken after the corresponding call. Missing
    GitHub CI provenance stays unknown; never guessed or authenticated anew.
    """
    repository = dict(TARGETS).get(name)
    if repository is None:
        raise ValueError("unknown target")
    journal = journal_reader()
    journal_at = clock()
    observed = status_reader(depth="deep")
    head = main_head(client, repository)
    head_at = clock()
    try:
        ci, run_id, pr_sha = _verified_pr_ci(client, repository, head)
    except (KeyError, TypeError, ValueError, OSError):
        ci, run_id, pr_sha = "unknown", None, None
    ci_at = clock()
    # ci_head_sha is an applicability mapping supported by the PR->merge
    # provenance above, never an assertion that Actions ran on squash SHA.
    result = development_evidence_v2(
        name, journal=journal, status_report=observed,
        github={"repository": repository, "head_sha": head,
                "ci_head_sha": head if ci == "success" else "0" * 40,
                "ci": ci, "head_observed_at": head_at,
                "ci_observed_at": ci_at},
        observed_at=journal_at, now=clock(), max_age_seconds=max_age_seconds,
    )
    result["ci_run"] = {"id": run_id, "pr_head_sha": pr_sha,
                        "main_sha": head, "relation": "merged_pr" if run_id is not None else "unknown"}
    return result
