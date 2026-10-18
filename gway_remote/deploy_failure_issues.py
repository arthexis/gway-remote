"""Create or refresh a single open deployment failure issue per repository.

Only sanitized artifact output is used. A successful run does not close issues:
an operator decides when the incident is resolved.
"""
import argparse
import json
from pathlib import Path
import subprocess

REPOSITORIES = {
    "ocpp_csms": "ocpp-csms",
    "ocpp_reports": "ocpp-reports",
    "ocpp_simulator": "ocpp-simulator",
    "gway_lcd_sound": "gway-lcd-sound",
    "gway_agent_ops": "gway-agent-ops",
    "gway_ap_kiosk": "gway-ap-kiosk",
    "gway_rfid": "gway-rfid",
}
MARKER = "<!-- gway-remote:deployment-failure:{name} -->"


def issue_body(name, outcome, run_url, summary, log_excerpt=""):
    marker = MARKER.format(name=name)
    body = [
        marker,
        f"## Deployment failure: `{name}`",
        "",
        f"**Latest run:** {run_url}",
        f"**Job result:** `{outcome}`",
        "",
        "This issue is refreshed after subsequent failed deployments of this component.",
        "A successful deployment does not automatically close it.",
        "",
        "### Sanitized appliance report",
        "",
        summary[:7000],
    ]
    if log_excerpt:
        body.extend(["", "### Sanitized recent installer output", "", "```text",
                     log_excerpt[-6000:], "```"])
    body.extend(["", "Full bounded sanitized logs are in the run's report artifact."])
    return "\n".join(body)


def gh_json(*args, input_text=None):
    cmd = ["gh", "api", *args]
    result = subprocess.run(cmd, input=input_text, capture_output=True,
                            text=True, check=True, timeout=30)
    return json.loads(result.stdout or "{}")


def upsert(repo, name, body):
    # Only update our own explicitly marked issues; do not rewrite unrelated incidents.
    issues = gh_json(f"repos/{repo}/issues", "-f", "state=open",
                     "-f", "per_page=100", "--method", "GET")
    matches = [item for item in issues
               if "pull_request" not in item and MARKER.format(name=name)
               in (item.get("body") or "")]
    if matches:
        issue = max(matches, key=lambda item: item["number"])
        return gh_json(f"repos/{repo}/issues/{issue['number']}", "--method", "PATCH",
                       "-f", f"body={body}")
    return gh_json(f"repos/{repo}/issues", "--method", "POST",
                   "-f", f"title=Appliance deployment failed: {name}",
                   "-f", f"body={body}")


def report_failures(repo, run_url, selected, job_results, report_dir):
    directory = Path(report_dir)
    summary = (directory / "summary.md").read_text(encoding="utf-8")
    report = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    components = {c["name"]: c for c in report["components"]}
    for job, name in REPOSITORIES.items():
        if selected != "all" and selected != name:
            continue
        outcome = job_results[job]["result"]
        if outcome not in ("failure", "cancelled", "timed_out"):
            continue
        component = components.get(name, {})
        logfile = component.get("log")
        excerpt = ""
        if logfile and Path(logfile).name == logfile:
            path = directory / "logs" / logfile
            if path.is_file() and not path.is_symlink():
                excerpt = path.read_text(encoding="utf-8", errors="replace")
        body = issue_body(name, outcome, run_url, summary, excerpt)
        issue = upsert(repo, name, body)
        print(f"{name}: {issue['html_url']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--selected", required=True)
    parser.add_argument("--job-results", required=True)
    parser.add_argument("--report-dir", required=True)
    args = parser.parse_args()
    report_failures(args.repo, args.run_url, args.selected,
                    json.loads(args.job_results), args.report_dir)


if __name__ == "__main__":
    main()


def report_manual_failures(result, *, repo="arthexis/gway-remote", directory=None):
    """Best-effort incident updates for direct operator CLI execution.

    Caller retains its original exit status even if GitHub is unavailable.
    """
    from .attempts import DEFAULT_DIR
    from .logs import sanitize

    directory = Path(directory or DEFAULT_DIR)
    links = []
    for item in result.get("results", []):
        if item.get("status") not in ("failed", "blocked"):
            continue
        name = item["name"]
        reason = sanitize(str(item.get("reason") or item.get("error") or "unknown"))[:500]
        excerpt = ""
        filename = item.get("log")
        if filename and Path(filename).name == filename:
            path = directory / "logs" / filename
            if path.is_file() and not path.is_symlink():
                excerpt = sanitize(path.read_text(encoding="utf-8", errors="replace"))[-6000:]
        sha = item.get("sha") or "unknown"
        summary = f"Operator-initiated CLI deployment\n\nAttempted SHA: {sha}\nReason: {reason}"
        body = issue_body(name, item["status"], "Direct operator CLI invocation (no Actions run)", summary, excerpt)
        issue = upsert(repo, name, body)
        links.append(issue["html_url"])
    return links
