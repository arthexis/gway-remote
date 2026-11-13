"""Create or refresh a single open deployment failure issue per repository.

Only sanitized artifact output is used. A successful run does not close issues:
an operator decides when the incident is resolved.
"""
import argparse
import json
from pathlib import Path
import subprocess

# The CLI dispatcher and the checked-in workflow must agree on this set.
# Do not list known-but-unadmitted repos (or guess missing job results).
from .deploy_dispatch import TARGETS as DISPATCH_TARGETS

REPOSITORIES = {
    name.replace("-", "_"): name
    for name in DISPATCH_TARGETS if name != "all"
}


def require_job_results(selected, job_results):
    """Validate the complete GitHub needs snapshot before any issue write."""
    if selected != "all" and selected not in REPOSITORIES.values():
        raise ValueError("unknown appliance deployment selection")
    if type(job_results) is not dict:
        raise ValueError("deployment job results must be an object")
    expected = set(REPOSITORIES) | {"admission"}
    if set(job_results) != expected:
        missing = sorted(expected - set(job_results))
        unexpected = sorted(set(job_results) - expected)
        raise ValueError(
            f"deployment job results mismatch: missing={missing}, unexpected={unexpected}"
        )
    valid_results = {"success", "failure", "cancelled", "skipped", "timed_out"}
    for job, value in job_results.items():
        if type(value) is not dict or value.get("result") not in valid_results:
            raise ValueError(f"invalid deployment result for {job}")
    if job_results["admission"]["result"] != "success":
        raise ValueError("deployment admission was not successful")
MARKER = "<!-- gway-remote:deployment-failure:{name} -->"


def issue_body(name, outcome, run_url, summary, log_excerpt="", diagnosis=None):
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
    if diagnosis:
        body.extend(["", "### Appliance diagnosis", "", "```json",
                     json.dumps(diagnosis, indent=2)[:3500], "```"])
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
    require_job_results(selected, job_results)
    directory = Path(report_dir)
    summary = (directory / "summary.md").read_text(encoding="utf-8")
    report = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    components = {c["name"]: c for c in report["components"]}
    diag_path = directory / "diagnostics.json"
    diagnostics = {}
    if diag_path.is_file() and not diag_path.is_symlink():
        evidence = json.loads(diag_path.read_text(encoding="utf-8"))
        diagnostics = {c["name"]: c for c in evidence.get("components", [])}
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
        evidence = diagnostics.get(name, {})
        concise = {key: evidence[key] for key in ("diagnosis", "diagnosis_reason", "health", "installation", "attempted_sha", "installed_sha", "systemd") if key in evidence}
        body = issue_body(name, outcome, run_url, summary, excerpt, concise)
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

