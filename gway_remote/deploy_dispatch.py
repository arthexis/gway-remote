"""Operator-triggered appliance deployment via GitHub Actions."""

import json
import os
import subprocess

REPOSITORY = "arthexis/gway-remote"
WORKFLOW = "appliance-deploy.yml"
from .reconcile import TARGETS as DEPLOYMENT_TARGETS

TARGETS = ("all", *(name for name, _ in DEPLOYMENT_TARGETS))


def dispatch(target: str) -> str:
    """Request the existing workflow; do not execute installers locally."""
    if target not in TARGETS:
        raise ValueError(f"Unknown deployment target: {target}")
    env = os.environ.copy()
    # gh accepts GH_TOKEN or an existing authenticated gh login.
    if not env.get("GH_TOKEN") and env.get("GITHUB_TOKEN"):
        env["GH_TOKEN"] = env["GITHUB_TOKEN"]
    try:
        result = subprocess.run(
            ["gh", "api", "--method", "POST",
             f"repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/dispatches",
             "-f", "ref=main", "-f", f"inputs[repository]={target}",
             "-F", "return_run_details=true"],
            env=env, check=True, text=True, capture_output=True, timeout=30,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("GitHub CLI (gh) is required") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("GitHub workflow dispatch timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise RuntimeError(f"GitHub workflow dispatch failed: {detail or exc.returncode}") from exc
    # GitHub returns an exact run ID when return_run_details is supported.
    # Never infer an ID by selecting the latest run (concurrent requests race).
    try:
        details = json.loads(result.stdout or "{}")
    except (ValueError, TypeError):
        details = {}
    run_id = details.get("workflow_run_id") if isinstance(details, dict) else None
    if isinstance(run_id, int) and run_id > 0:
        return (f"Requested {target} deployment: workflow run {run_id}\n"
                f"https://github.com/{REPOSITORY}/actions/runs/{run_id}"
                " (request accepted; installation result pending)")
    return (f"Requested {target} deployment through "
            f"https://github.com/{REPOSITORY}/actions/workflows/{WORKFLOW}"
            " (request accepted; run ID unavailable; installation result pending)")


def follow_run(message: str) -> None:
    """Watch only the exact run returned by the dispatch response.

    GitHub CLI renders live job/step progress to the operator's terminal.
    No fallback to an ambiguous 'latest run' is permitted.
    """
    import re
    match = re.search(r"workflow run ([1-9][0-9]*)\n", message)
    if match is None:
        raise RuntimeError(
            "Cannot follow deployment: GitHub did not return a workflow run ID. "
            "Use the workflow URL above to inspect the request."
        )
    run_id = match.group(1)
    try:
        subprocess.run(
            ["gh", "run", "watch", run_id, "--repo", REPOSITORY,
             "--exit-status", "--interval", "3"],
            check=True, timeout=7200,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("GitHub CLI (gh) is required to follow deployments") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Timed out following deployment run {run_id}; it may still be running") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Deployment run {run_id} failed or could not be watched (exit {exc.returncode})") from exc
