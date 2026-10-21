"""Read-only bounded Follow snapshot for one durable deployment request."""
from .mobile_deploy_dispatch import observe, IDENTIFIER
from .reconcile import TARGETS
from .github_state import GitHub
from .attempts import read_attempts
from .status import installed_revision
from .logs import sanitize
from pathlib import Path
import re

JOB_NAMES = {name.replace("-", "_"): name for name, _ in TARGETS}
TERMINAL = frozenset({"completed"})
ALLOWED_JOB_STATUS = frozenset({"queued", "in_progress", "completed", "waiting", "pending"})


def snapshot(arguments, *, observer=observe, client_factory=GitHub,
             attempts_reader=read_attempts, revision_reader=installed_revision,
             log_root=None):
    if type(arguments) is not dict or set(arguments) != {"request_id"}:
        raise ValueError("invalid_deployment_arguments")
    key = arguments["request_id"]
    if type(key) is not str or not IDENTIFIER.fullmatch(key):
        raise ValueError("invalid_deployment_request_id")
    admission = observer({"request_id": key})
    run_id = admission.get("run_id")
    base = {"schema": 1, "request_id": key, "target": admission["target"],
            "run_id": run_id, "workflow_url": admission.get("workflow_url"),
            "state": admission["state"], "conclusion": None,
            "repositories": [], "events": [], "resumable": True}
    if type(run_id) is not int or run_id < 1:
        return base
    client = client_factory()
    repo = "repos/arthexis/gway-remote/actions/runs/" + str(run_id)
    run = client.get(repo)
    if run.get("id") != run_id or run.get("event") != "workflow_dispatch":
        raise RuntimeError("deployment_run_identity_mismatch")
    jobs_data = client.get(repo + "/jobs?per_page=100")
    jobs = jobs_data.get("jobs")
    if type(jobs) is not list:
        raise RuntimeError("deployment_jobs_unavailable")
    selected = [name for name, _ in TARGETS] if admission["target"] == "all" else [admission["target"]]
    report = {name: {"name": name, "state": "queued", "conclusion": None,
                     "started_at": None, "completed_at": None, "steps": []}
              for name in selected}
    seen = set()
    for job in jobs:
        if type(job) is not dict:
            continue
        keyname = job.get("name")
        # Jobs have stable workflow job names, not repository-derived arbitrary shell data.
        name = keyname.removeprefix("Deploy ") if type(keyname) is str else None
        if name == "gway-bastion (stage-only)":
            name = "gway-bastion"
        if name not in report or name in seen:
            continue
        seen.add(name)
        status = job.get("status")
        if status not in ALLOWED_JOB_STATUS:
            status = "unknown"
        steps = job.get("steps")
        safe_steps = []
        if type(steps) is list:
            for step in steps[:24]:
                if type(step) is not dict:
                    continue
                # Step text can be attacker-controlled. Expose only ordinal and
                # GitHub's normalized outcome; do not return raw logs or step names.
                safe_steps.append({"number": step.get("number") if type(step.get("number")) is int else None,
                                   "state": step.get("status") if step.get("status") in ALLOWED_JOB_STATUS else "unknown",
                                   "conclusion": step.get("conclusion") if step.get("conclusion") in ("success", "failure", "skipped", "cancelled") else None})
        report[name] = {"name": name, "state": status,
                        "conclusion": job.get("conclusion") if job.get("conclusion") in ("success", "failure", "cancelled", "skipped") else None,
                        "started_at": job.get("started_at"), "completed_at": job.get("completed_at"),
                        "steps": safe_steps}
    # Appliance journal describes the latest observed attempt, not necessarily
    # this Actions run. Never silently attribute it to the current workflow.
    attempts = attempts_reader()
    for name, row in report.items():
        record = attempts.get(name)
        row["installed_sha"] = revision_reader(name)
        row["last_appliance_attempt"] = None
        row["diagnostic_tail"] = []
        if type(record) is not dict:
            continue
        sha = record.get("sha")
        state = record.get("status")
        if not (type(sha) is str and re.fullmatch(r"[0-9a-f]{40}", sha)
                and state in ("started", "installed", "staged", "failed")):
            continue
        row["last_appliance_attempt"] = {
            "sha": sha, "state": state, "at": record.get("at"),
            "associated_with_this_run": False,
        }
        # Only the filename recorded by the journal is eligible; never take
        # an unrelated latest log or follow a symlink.
        filename = record.get("log")
        if type(filename) is not str or not re.fullmatch(
                r"[0-9TZ]+-" + re.escape(name) + r"-[0-9a-f]{12}\\.log", filename):
            continue
        if not filename.endswith("-" + sha[:12] + ".log"):
            continue
        from .attempts import DEFAULT_DIR
        folder = Path(log_root) if log_root is not None else DEFAULT_DIR / "logs"
        log = folder / filename
        if log.is_symlink() or not log.is_file():
            continue
        with log.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 8192))
            tail = stream.read(8192).decode("utf-8", errors="replace")
        # Do not echo untrusted log content to mobile. Return only strictly
        # allowlisted, sanitized milestones from that bounded tail.
        patterns = ("PLAY RECAP", "TASK [", "fatal:", "Installer failure",
                    "Bastion release staged only")
        row["diagnostic_tail"] = [
            "Ansible task" if line.startswith("TASK [") else
            "Deployment failure" if "fatal:" in line or "Installer failure" in line else
            "Ansible recap" if "PLAY RECAP" in line else
            "Bastion staged" for line in tail.splitlines()
            if any(token in line for token in patterns)
        ][-12:]
    base["repositories"] = list(report.values())
    base["state"] = "completed" if run.get("status") == "completed" else "running" if run.get("status") == "in_progress" else "queued" if run.get("status") == "queued" else "unknown"
    base["conclusion"] = run.get("conclusion") if run.get("conclusion") in ("success", "failure", "cancelled", "timed_out") else None
    base["events"] = [{"repository": row["name"], "state": row["state"], "conclusion": row["conclusion"]}
                      for row in base["repositories"]]
    return base
