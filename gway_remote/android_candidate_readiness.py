"""Hosted candidate-aware PR readiness. Never allocate, install, sign or publish.

This is an advisory status until the owner separately enables its reviewed
ruleset context. Strict CI continues to be the required integration guard.
"""
import argparse
import os
from gway_remote import android_release_gate as gate

CONTEXT = "Android candidate readiness"
WORKFLOWS = {
    379902233: ("ci.yml", "CI"),
    380937066: ("android.yml", "build"),
    389039485: ("android-compose-ui.yml", "compose-ui"),
}
# A PR may not certify itself by changing the evidence producer. Such
# changes need a separately reviewed trusted workflow transition.
EVIDENCE_CONTROL = {".github/workflows/" + name for name, _ in WORKFLOWS.values()} | {
    "android/scripts/run-compose-ui-tests.sh", "gway_remote/android_rc_contracts.py",
}
MAX_PRS = 50


def exact_pr(pr, *, api=gate.api):
    p = api(f"pulls/{pr}")
    base, head = p["base"], p["head"]
    gate.require(p["state"] == "open" and base["ref"] == "main"
                 and (base.get("repo") or {}).get("full_name") == gate.REPO
                 and gate.SHA.fullmatch(base["sha"]) and gate.SHA.fullmatch(head["sha"])
                 and api("branches/main")["commit"]["sha"] == base["sha"],
                 "PR or base moved")
    return p


def exact_paths(p, *, pages=gate.pages):
    rows = pages(f"pulls/{p['number']}/files?per_page=100")
    gate.require(type(p["changed_files"]) is int and 0 < len(rows) == p["changed_files"] < 3000,
                 "changed-file evidence incomplete")
    names = set()
    for row in rows:
        path = row.get("filename")
        prior = row.get("previous_filename")
        gate.require(isinstance(path, str) and path and path not in names
                     and not path.startswith("/") and "\x00" not in path,
                     "invalid changed-file evidence")
        gate.require(row.get("status") != "renamed" or isinstance(prior, str) and prior,
                     "rename evidence missing")
        names.add(path)
        if prior:
            gate.require(isinstance(prior, str) and not prior.startswith("/")
                         and "\x00" not in prior, "invalid rename evidence")
            names.add(prior)
    return names


def identity(p):
    return (p["number"], p["head"]["sha"], p["base"]["sha"],
            (p["head"].get("repo") or {}).get("full_name"), p["draft"])


def exact_hosted(p, workflow_id, *, api=gate.api):
    workflow, required_job = WORKFLOWS[workflow_id]
    head, base = p["head"]["sha"], p["base"]["sha"]
    listing = api(f"actions/workflows/{workflow_id}/runs?event=pull_request&head_sha={head}&per_page=100")
    rows = listing["workflow_runs"]
    gate.require(listing["total_count"] == len(rows), "incomplete hosted run evidence")
    def belongs(r):
        return (r.get("workflow_id") == workflow_id
                and r.get("path") == ".github/workflows/" + workflow
                and (r.get("repository") or {}).get("full_name") == gate.REPO
                and (r.get("head_repository") or {}).get("full_name") == gate.REPO
                and r.get("event") == "pull_request" and r.get("head_sha") == head
                and any(x.get("number") == p["number"]
                        and (x.get("head") or {}).get("sha") == head
                        and (x.get("base") or {}).get("sha") == base
                        for x in r.get("pull_requests", [])))
    found = [r for r in rows if belongs(r)]
    if not found:
        return "pending"
    # Never fall back to an earlier green run after a newer attempt failed.
    run = max(found, key=lambda r: (r["run_number"], r["id"]))
    if run.get("status") != "completed":
        return "pending"
    if run.get("conclusion") != "success":
        return "failure"
    current = api(f"actions/runs/{run['id']}")
    gate.require(belongs(current) and current.get("status") == "completed"
                 and current.get("conclusion") == "success"
                 and current.get("run_attempt") == run.get("run_attempt")
                 and type(current.get("run_attempt")) is int,
                 "hosted run changed or untrusted")
    result = api(f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100")
    jobs = result["jobs"]
    gate.require(result["total_count"] == len(jobs), "incomplete hosted jobs")
    matching = [j for j in jobs if j.get("name") == required_job]
    if len(matching) != 1 or matching[0].get("conclusion") != "success":
        return "failure"
    return "success"


def evaluate(p, paths, *, api=gate.api):
    if not gate.android_changed(paths):
        return "success", "not-applicable"
    if p["draft"] or (p["head"].get("repo") or {}).get("full_name") != gate.REPO:
        return "pending", "owner-review"
    if paths & EVIDENCE_CONTROL:
        return "pending", "trusted-workflow-transition"
    base, head = p["base"]["sha"], p["head"]["sha"]
    compare = api(f"compare/{base}...{head}")
    if (compare.get("merge_base_commit") or {}).get("sha") != base:
        return "pending", "integrate-main"
    states = [exact_hosted(p, wid, api=api) for wid in WORKFLOWS]
    if "failure" in states:
        return "failure", "hosted-checks-failed"
    if any(s != "success" for s in states):
        return "pending", "hosted-checks-pending"
    return "success", "hosted-ready"


def report(head, base, state, reason, url):
    gate.require(state in {"success", "pending", "failure"} and gate.SHA.fullmatch(head)
                 and gate.SHA.fullmatch(base), "invalid readiness status")
    gate.gh("api", f"repos/{gate.REPO}/statuses/{head}", "-f", f"state={state}",
            "-f", f"context={CONTEXT}", "-f", f"description={reason} base={base}",
            "-f", f"target_url={url}")


def reconcile(pr, url, *, api=gate.api, pages=gate.pages, write=report):
    p = exact_pr(pr, api=api)
    head, base = p["head"]["sha"], p["base"]["sha"]
    def same():
        gate.require(identity(exact_pr(pr, api=api)) == identity(p), "PR identity changed")
    same()
    write(head, base, "pending", "evaluating", url)
    try:
        paths = exact_paths(p, pages=pages)
        state, reason = evaluate(p, paths, api=api)
        same()
        # Re-read changed files as well: never report on incomplete or changed data.
        gate.require(exact_paths(exact_pr(pr, api=api), pages=pages) == paths,
                     "changed-file evidence moved")
        same()
    except Exception:
        same()
        write(head, base, "failure", "evidence-unverified", url)
        raise
    write(head, base, state, reason, url)
    return state, reason


def reconcile_all(url, *, api=gate.api, pages=gate.pages, write=report):
    rows = api("pulls?state=open&base=main&per_page=100")
    gate.require(isinstance(rows, list) and len(rows) <= MAX_PRS,
                 "open PR count exceeds reviewed reconciliation bound")
    failed = []
    for row in rows:
        pr = row["number"]
        try:
            state, reason = reconcile(pr, url, api=api, pages=pages, write=write)
            print(f"PR #{pr}: {state} {reason}")
        except Exception:
            failed.append(pr)
            print(f"PR #{pr}: evidence unavailable")
    gate.require(not failed, "one or more PR classifications unavailable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    gate.require(os.environ.get("GITHUB_REPOSITORY") == gate.REPO
                 and args.run_id > 0, "unexpected workflow repository")
    reconcile_all(f"https://github.com/{gate.REPO}/actions/runs/{args.run_id}")


if __name__ == "__main__":
    main()
