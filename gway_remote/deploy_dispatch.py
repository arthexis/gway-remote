"""Operator-triggered appliance deployment via GitHub Actions."""

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
        subprocess.run(
            ["gh", "workflow", "run", WORKFLOW, "--repo", REPOSITORY,
             "--ref", "main", "-f", f"repository={target}"],
            env=env, check=True, text=True, capture_output=True, timeout=30,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("GitHub CLI (gh) is required") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("GitHub workflow dispatch timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise RuntimeError(f"GitHub workflow dispatch failed: {detail or exc.returncode}") from exc
    return (f"Requested {target} deployment through "
            f"https://github.com/{REPOSITORY}/actions/workflows/{WORKFLOW}"
            " (request accepted; installation result pending)")
