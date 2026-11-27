"""Trusted-main Android release orchestration; no PR code is executed here."""
import base64
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from gway_remote.android_canary_field import provenance

REPO = "arthexis/gway-remote"
OWNER = "arthexis"
CONTEXT = "Android acceptance"
SHA = re.compile(r"[0-9a-f]{40}\Z")
ANDROID_WORKFLOWS = {"android.yml", "android-compose-ui.yml"}
CHECKS = {"ci.yml": "CI", "android.yml": "build", "android-compose-ui.yml": "compose-ui"}


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def gh(*args, timeout=90):
    return subprocess.check_output(["gh", *args], text=True, timeout=timeout, stderr=subprocess.PIPE).strip()


def api(path, *args, timeout=90):
    return json.loads(gh("api", f"repos/{REPO}/{path}", *args, timeout=timeout))


def pages(path):
    return [item for page in json.loads(gh("api", "--paginate", "--slurp",
                                           f"repos/{REPO}/{path}")) for item in page]


def android_changed(paths):
    return any(p.startswith("android/") or p in
               {f".github/workflows/{w}" for w in ANDROID_WORKFLOWS} for p in paths)


def release_issues(body):
    # GitHub closes keyword-linked issues at merge, which is too early.
    require(not re.search(r"(?i)\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\s*:?\s+(?:[\w.-]+/[\w.-]+)?#\d+|\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\s*:?\s+https://github\.com/", body),
            "remove closing keywords; use Release-Issue: #N")
    return sorted({int(n) for n in re.findall(r"(?m)^Release-Issue: #([1-9]\d{0,6})\s*$", body)})


def current(pr, sha, base=None):
    p = api(f"pulls/{pr}")
    require(p["state"] == "open" and not p["draft"] and p["base"]["ref"] == "main"
            and p["head"]["repo"] and p["head"]["repo"]["full_name"] == REPO
            and p["head"]["sha"] == sha, "PR moved or not eligible")
    if base:
        require(p["base"]["sha"] == base and api("branches/main")["commit"]["sha"] == base,
                "base moved; reapprove integrated head")
    return p


def changed(pr):
    p = api(f"pulls/{pr}")
    rows = pages(f"pulls/{pr}/files?per_page=100")
    require(len(rows) == p["changed_files"], "incomplete changed files")
    return {name for row in rows for name in
            (row["filename"], row.get("previous_filename")) if name}


def status(sha, state, description, url):
    gh("api", f"repos/{REPO}/statuses/{sha}", "-f", f"state={state}",
       "-f", f"context={CONTEXT}", "-f", f"description={description}", "-f", f"target_url={url}")


def verify_run_identity(run, workflow, run_id, event, sha=None):
    require(run.get("id") == run_id
            and (run.get("repository") or {}).get("full_name") == REPO
            and run.get("path") == f".github/workflows/{workflow}"
            and run.get("event") == event
            and (event != "workflow_dispatch" or
                 (run.get("head_branch") == "main" and
                  (run.get("head_repository") or {}).get("full_name") == REPO))
            and bool(SHA.fullmatch(run.get("head_sha") or ""))
            and (sha is None or run["head_sha"] == sha),
            f"unexpected workflow identity for run {run_id}")


def wait_run(workflow, run_id, event, sha=None, timeout=1800):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        r = api(f"actions/runs/{run_id}")
        verify_run_identity(r, workflow, run_id, event, sha)
        if r["status"] == "completed":
            require(r["conclusion"] == "success", f"{workflow} failed")
            return r
        time.sleep(15)
    raise RuntimeError(f"{workflow} timed out")


def await_dispatch_visibility(workflow, run_id, sha=None):
    """Read the exact created run with the dispatch credential; never create again."""
    deadline = time.monotonic() + 135
    for attempt in range(9):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            run = api(f"actions/runs/{run_id}", timeout=min(15, remaining))
        except subprocess.CalledProcessError as exc:
            if "HTTP 404" not in (exc.stderr or ""):
                raise
            if attempt == 8:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(15, remaining))
            continue
        verify_run_identity(run, workflow, run_id, "workflow_dispatch", sha)
        return run
    raise RuntimeError(f"Dispatched {workflow} run {run_id} not visible within bound; "
                       "reconcile this ID before another dispatch")


def create_run(workflow, **inputs):
    # Dispatch is a mutation: no retries, including uncertain CLI failures.
    out = subprocess.check_output(
                 ["gh", "workflow", "run", workflow, "-R", REPO, "--ref", "main", "--json"],
                 input=json.dumps(inputs), text=True, timeout=90).strip()
    m = re.fullmatch(rf"https://github[.]com/{re.escape(REPO)}/actions/runs/([1-9][0-9]*)", out)
    require(m, "dispatch did not return exact repository run URL; reconcile before retry")
    return int(m.group(1))


def dispatch(workflow, **inputs):
    run_id = create_run(workflow, **inputs)
    print(f"Dispatched {workflow} run {run_id}; checking visibility", flush=True)
    # For canaries expected_sha identifies the PR artifact, not the main workflow.
    # Production release dispatch pins the workflow revision itself.
    sha = inputs.get("expected_sha") if workflow in (
        "android.yml", "android-release-candidate.yml", "android-release-candidate-sign.yml"
    ) else None
    await_dispatch_visibility(workflow, run_id, sha)
    return run_id


def pr_ci(pr, sha, base):
    for workflow, job in CHECKS.items():
        runs = api(f"actions/workflows/{workflow}/runs?event=pull_request&head_sha={sha}&per_page=30")["workflow_runs"]
        matches = [r for r in runs if r["head_sha"] == sha and
                   any(p["number"] == pr and p["base"]["sha"] == base for p in r["pull_requests"])]
        require(matches, f"missing {workflow} for exact PR HEAD")
        r = wait_run(workflow, matches[0]["id"], "pull_request", sha)
        jobs = api(f"actions/runs/{r['id']}/jobs?per_page=100")["jobs"]
        require(any(j["name"] == job and j["conclusion"] == "success" for j in jobs),
                f"required job absent: {job}")


def verify_receipt(receipt, pr, sha, build_id, install_id, minimum):
    require(receipt.get("pr") == pr and receipt.get("source_sha") == sha
            and receipt.get("run_id") == build_id and receipt.get("install_run_id") == install_id
            and receipt.get("suite") == "baseline" and receipt.get("status") == "passed"
            and type(receipt.get("tests_passed")) is int and receipt["tests_passed"] >= minimum
            and receipt.get("production_package_unchanged") is True,
            "physical receipt mismatch")


def download(run_id, name, directory):
    gh("run", "download", str(run_id), "-R", REPO, "--name", name, "--dir", str(directory))


def physical(pr, sha, reset, authorization):
    build = dispatch("android-canary.yml", pr_number=str(pr), expected_sha=sha)
    wait_run("android-canary.yml", build, "workflow_dispatch")
    with tempfile.TemporaryDirectory() as d:
        download(build, f"android-canary-pr{pr}-{sha[:12]}", d)
        hashes = provenance(d, pr=pr, sha=sha, run_id=build)
    current(pr, sha)
    install = dispatch("android-canary-install.yml", pr_number=str(pr), expected_sha=sha,
                       artifact_run_id=str(build), apk_sha256=hashes["gway-remote-canary.apk"],
                       canary_reset=reset, run_compose_tests="RUN_HERMETIC_TESTS",
                       compose_suite="baseline", run_feed_tests="no",
                       authorization_run_id=str(authorization))
    wait_run("android-canary-install.yml", install, "workflow_dispatch", timeout=900)
    with tempfile.TemporaryDirectory() as d:
        download(install, f"android-physical-receipt-{install}", d)
        receipt = json.loads((Path(d) / "receipt.json").read_text())
    verify_receipt(receipt, pr, sha, build, install, 6)
    return receipt


def assert_publication_ready():
    workflow = api("contents/.github/workflows/android.yml?ref=main")
    require(workflow.get("encoding") == "base64", "cannot verify publication policy")
    source = base64.b64decode(workflow["content"]).decode("utf-8")
    require("ANDROID_PUBLICATION_HOLD_718" not in source,
            "Android publication suspended by staged CRM rollout #718")
    require("LEGACY_ANDROID_PUBLISHER_RETIRED" not in source,
            "Legacy publication retired; use exact-artifact promotion")


def assert_gate_required():
    rules = api("rules/branches/main")
    required = [c for r in rules if r["type"] == "required_status_checks"
                and r["parameters"]["strict_required_status_checks_policy"]
                for c in r["parameters"]["required_status_checks"]]
    require(all(any(c["context"] == name and c.get("integration_id") == 15368 for c in required)
                for name in ("CI", CONTEXT)), "strict CI + Android gate not active")


def issue_links(pr, p):
    release_issues(p.get("title") or "")
    issues = release_issues(p.get("body") or "")
    linked = json.loads(gh("pr", "view", str(pr), "-R", REPO, "--json", "closingIssuesReferences"))
    require(not linked["closingIssuesReferences"], "GitHub automatic issue closure is linked")
    commits = pages(f"pulls/{pr}/commits?per_page=100")
    require(len(commits) == p["commits"], "incomplete PR commit list")
    for commit in commits:
        release_issues(commit["commit"]["message"])
    for n in issues:
        row = api(f"issues/{n}")
        require("pull_request" not in row and row["state"] == "open", "release issue not open")
    return issues


def conditional(pr, sha, url):
    p = api(f"pulls/{pr}")
    require(p["head"]["sha"] == sha and p["base"]["ref"] == "main", "obsolete event")
    paths = changed(pr)
    require(api(f"pulls/{pr}")["head"]["sha"] == sha, "obsolete classification")
    if android_changed(paths):
        status(sha, "pending", "Owner acceptance required for Android", url)
    else:
        status(sha, "success", "No Android changes", url)


def accept(pr, sha, base, reset, authorization, merge, minimum, url):
    p = current(pr, sha, base)
    require(p["user"]["login"] == OWNER, "owner-authored PR required")
    paths = changed(pr)
    require(android_changed(paths), "not an Android PR")
    require(api(f"compare/{base}...{sha}")["merge_base_commit"]["sha"] == base,
            "integrate main first")
    approved_issues = issue_links(pr, p)
    if merge:
        require(all(android_changed([path]) for path in paths),
                "mixed backend PR requires normal merge to preserve deployment triggers")
        assert_gate_required()
        assert_publication_ready()
    status(sha, "pending", "Validating pinned Android revision", url)
    try:
        pr_ci(pr, sha, base)
        receipt = physical(pr, sha, reset, authorization)
        verify_receipt(receipt, pr, sha, receipt["run_id"], receipt["install_run_id"], minimum)
        require(issue_links(pr, current(pr, sha, base)) == approved_issues, "release links changed")
        pr_ci(pr, sha, base)
    except Exception:
        status(sha, "failure", "Android acceptance failed; inspect run", url)
        raise
    status(sha, "success", "CI and physical canary passed", url)
    if not merge:
        return
    assert_gate_required()
    assert_publication_ready()
    current(pr, sha, base)
    for _ in range(12):
        current(pr, sha, base)
        m = json.loads(gh("pr", "view", str(pr), "-R", REPO, "--json", "autoMergeRequest,mergeStateStatus"))
        require(m["autoMergeRequest"] is None, "existing auto-merge request")
        if m["mergeStateStatus"] == "CLEAN":
            break
        time.sleep(10)
    else:
        raise RuntimeError("PR not clean; auto-merge not armed")
    require(issue_links(pr, current(pr, sha, base)) == approved_issues, "release links changed")
    message = f"Android acceptance passed for {sha}.\n\n" + "\n".join(f"Release-Issue: #{n}" for n in approved_issues)
    gh("pr", "merge", str(pr), "-R", REPO, "--auto", "--merge", "--match-head-commit", sha,
       "--subject", f"Merge Android PR #{pr}", "--body", message)
    for _ in range(20):
        p = api(f"pulls/{pr}")
        if p["merged"]:
            break
        time.sleep(10)
    else:
        gh("pr", "merge", str(pr), "-R", REPO, "--disable-auto")
        raise RuntimeError("merge unconfirmed; auto-merge disabled")
    merged = p["merge_commit_sha"]
    require(SHA.fullmatch(merged) and p["head"]["sha"] == sha, "merged revision mismatch")
    require(api("branches/main")["commit"]["sha"] == merged, "main advanced before release")
    # GITHUB_TOKEN merges may not emit normal push-triggered Actions.
    time.sleep(15)
    runs = api(f"actions/workflows/android.yml/runs?head_sha={merged}&per_page=20")["workflow_runs"]
    existing = [r for r in runs if r["event"] in ("push", "workflow_dispatch") and r["head_branch"] == "main"]
    run_id = existing[0]["id"] if existing else dispatch("android.yml", expected_sha=merged)
    wait_run("android.yml", run_id, existing[0]["event"] if existing else "workflow_dispatch", merged)
    jobs = api(f"actions/runs/{run_id}/jobs?per_page=100")["jobs"]
    require(any(j["name"] == "publish" and j["conclusion"] == "success" for j in jobs), "publication job not verified")
    for n in release_issues(p.get("body") or ""):
        require(api(f"issues/{n}")["state"] == "closed", f"release issue #{n} not closed")
    print(f"Verified publication workflow {run_id} for {merged}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("conditional", "accept"))
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--base")
    parser.add_argument("--reset", choices=("no", "RESET_CANARY_ONLY"), default="no")
    parser.add_argument("--authorization", type=int)
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--minimum", type=int, default=6)
    parser.add_argument("--url", required=True)
    a = parser.parse_args()
    require(0 < a.pr < 10000000 and SHA.fullmatch(a.sha), "invalid PR or SHA")
    if a.mode == "conditional":
        conditional(a.pr, a.sha, a.url)
    else:
        require(a.base and SHA.fullmatch(a.base) and a.authorization and a.minimum >= 6,
                "invalid acceptance authorization")
        accept(a.pr, a.sha, a.base, a.reset, a.authorization, a.merge, a.minimum, a.url)
