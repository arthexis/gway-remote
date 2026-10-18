"""Bounded appliance reconciliation. Single tick, no resident daemon.

A target is auto-deployable only when its installed revision is independently
verified, CI for the new main SHA passed, and that SHA has never been attempted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import json
import os
import subprocess

from .attempts import read_attempts
from .deployments import inventory
from .deploy_dispatch import dispatch
from .github_state import GitHub, ci_for_head, main_arrival
from .diagnostics import diagnose
from .reconcile import TARGETS

ISSUE_MARKER = "<!-- gway-remote:appliance-watch:{name}:{kind} -->"
COOLDOWN = timedelta(minutes=10)


def eligible(row, ci, merged_at, now):
    """Conservative pure decision; never redeploy an attempted revision."""
    if row["revision_status"] != "behind":
        return False
    if row["attempted_sha"] and row["attempted_sha"].lower() == row["latest_sha"].lower():
        return False
    if row["attempt_status"] in {"failed", "started"} and row["attempted_sha"] == row["latest_sha"]:
        return False
    if ci != "success" or merged_at is None:
        return False
    return now - merged_at.astimezone(timezone.utc) >= COOLDOWN


def _api(*args, input_text=None):
    result = subprocess.run(["gh", "api", *args], input=input_text,
                            text=True, capture_output=True, check=True, timeout=25)
    return json.loads(result.stdout or "{}")


def _busy():
    """Never add a dispatch while the appliance workflow has outstanding runs."""
    repo = "arthexis/gway-remote"
    for state in ("queued", "in_progress", "waiting", "requested"):
        data = _api(f"repos/{repo}/actions/workflows/appliance-deploy.yml/runs",
                    "--method", "GET", "-f", f"status={state}", "-f", "per_page=10")
        if data.get("total_count", 0):
            return True
    return False


def _issue(repo, name, kind, reason):
    marker = ISSUE_MARKER.format(name=name, kind=kind)
    title = f"Appliance {kind}: {name}"
    # Never upload installer logs, credentials, environment or remote traces.
    body = f"{marker}\n## {title}\n\n{reason[:500]}\n\nSource: gway-remote appliance watch."
    existing = _api(f"repos/{repo}/issues", "--method", "GET",
                    "-f", "state=open", "-f", "per_page=100")
    matches = [item for item in existing if "pull_request" not in item
               and marker in (item.get("body") or "")]
    if matches:
        item = matches[-1]
        if item.get("body") == body:
            return
        _api(f"repos/{repo}/issues/{item['number']}", "--method", "PATCH",
             "-f", f"body={body}")
    else:
        _api(f"repos/{repo}/issues", "--method", "POST",
             "-f", f"title={title}", "-f", f"body={body}")


def _github_client():
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        # Systemd sessions do not automatically export the gh token.
        # Never log or print the credential returned by this command.
        response = subprocess.run(["gh", "auth", "token"], capture_output=True,
                                  text=True, check=True, timeout=10)
        token = response.stdout.strip()
    if not token:
        raise RuntimeError("GitHub authentication unavailable for appliance watch")
    return GitHub(token=token)


def check(*, apply=False, client=None, now=None):
    client = client if client is not None else _github_client()
    now = now or datetime.now(timezone.utc)
    attempts = read_attempts()  # Corrupt evidence aborts, never triggers installs.
    report = inventory(client=client, attempts=attempts)
    observations = {x["name"]: x for x in diagnose()["components"]}
    decisions = []
    pending = []
    sources = dict(TARGETS)
    for row in report["components"]:
        name = row["name"]
        observation = observations[name]
        category = observation["diagnosis"]
        if category in {"runtime-failed", "health-check-failed"}:
            decisions.append({"name": name, "state": "intrinsic-failure"})
            if apply:
                _issue(sources[name], name, "runtime-failure",
                       observation.get("diagnosis_reason", "Runtime check failed"))
            continue
        if row["revision_status"] == "unknown":
            decisions.append({"name": name, "state": "unverified-revision"})
            continue
        if row["revision_status"] == "current":
            decisions.append({"name": name, "state": "current"})
            continue
        ci = ci_for_head(client, sources[name], row["latest_sha"])
        arrival = main_arrival(client, sources[name], row["latest_sha"])
        if eligible(row, ci, arrival, now):
            pending.append(name)
            decisions.append({"name": name, "state": "ready"})
        else:
            decisions.append({"name": name, "state": "blocked",
                              "reason": "CI, cooldown or already-attempted revision"})
    dispatched = None
    if apply and pending:
        if not _busy():
            # Only one request per tick. The existing workflow owns serialization.
            dispatched = pending[0]
            try:
                dispatch(dispatched)
            except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
                _issue("arthexis/gway-remote", dispatched, "dispatch-failure",
                       "Appliance workflow dispatch was rejected or unavailable")
                raise
    return {"schema": "gway-remote/watch/v1", "checked_at": now.isoformat(),
            "decisions": decisions, "dispatched": dispatched}


def main():
    parser = argparse.ArgumentParser(description="One bounded appliance reconciliation tick")
    parser.add_argument("--apply", action="store_true",
                        help="Enable workflow dispatch and deduplicated issue writes")
    args = parser.parse_args()
    print(json.dumps(check(apply=args.apply), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
