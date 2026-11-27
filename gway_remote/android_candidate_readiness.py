"""Hosted candidate-aware PR readiness. Never allocate, install, sign or publish.

This is an advisory status until the owner separately enables its reviewed
ruleset context. Strict CI continues to be the required integration guard.
"""
import argparse
import copy
import os
import subprocess
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
    gate.require(belongs(current) and current.get("id") == run["id"]
                 and current.get("run_number") == run["run_number"]
                 and current.get("status") == "completed"
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


def reconcile(pr, url, *, trusted_base=None, api=gate.api, pages=gate.pages, write=report):
    p = exact_pr(pr, api=api)
    head, base = p["head"]["sha"], p["base"]["sha"]
    gate.require(trusted_base is None or trusted_base == base, "trusted workflow base moved")
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


def reconcile_all(url, *, trusted_base=None, api=gate.api, pages=gate.pages, write=report):
    rows = api("pulls?state=open&base=main&per_page=100")
    gate.require(isinstance(rows, list) and len(rows) <= MAX_PRS,
                 "open PR count exceeds reviewed reconciliation bound")
    failed = []
    for row in rows:
        pr = row["number"]
        try:
            state, reason = reconcile(pr, url, trusted_base=trusted_base, api=api, pages=pages, write=write)
            print(f"PR #{pr}: {state} {reason}")
        except Exception:
            failed.append(pr)
            print(f"PR #{pr}: evidence unavailable")
    gate.require(not failed, "one or more PR classifications unavailable")



def ruleset_plan(existing):
    """Pure additive plan only; no rule mutation or bypass is permitted."""
    rule = copy.deepcopy({k: existing[k] for k in
                          ("name", "target", "enforcement", "bypass_actors", "conditions", "rules")})
    gate.require(rule["name"] == "main" and rule["target"] == "branch"
                 and rule["enforcement"] == "active" and not rule["bypass_actors"],
                 "unexpected branch ruleset")
    checks = [x for x in rule["rules"] if x["type"] == "required_status_checks"]
    gate.require(len(checks) == 1, "ambiguous required status checks")
    params = checks[0]["parameters"]
    required = params["required_status_checks"]
    expected = {"context": CONTEXT, "integration_id": 15368}
    gate.require(params["strict_required_status_checks_policy"] is True
                 and {"context": "CI", "integration_id": 15368} in required,
                 "existing strict CI missing")
    found = [x for x in required if x["context"] == CONTEXT]
    gate.require(not found or found == [expected], "wrong gate integration")
    if not found:
        required.append(expected)
    return rule


def merge_plan(pr, head, base, *, owner_opt_in, actor, api=gate.api, pages=gate.pages):
    """Preflight only; never arm a latent merge or dispatch a candidate."""
    gate.require(owner_opt_in is True and actor == gate.OWNER, "owner opt-in required")
    p = exact_pr(pr, api=api)
    gate.require(not p["draft"] and p["head"]["sha"] == head and p["base"]["sha"] == base
                 and (p["head"].get("repo") or {}).get("full_name") == gate.REPO
                 and (p.get("user") or {}).get("login") == gate.OWNER, "owner PR moved")
    paths = exact_paths(p, pages=pages)
    gate.require(all(x.startswith("android/") for x in paths), "mixed/control-plane PR requires protected normal merge")
    gate.require(evaluate(p, paths, api=api) == ("success", "hosted-ready"), "hosted evidence not ready")
    rules = api("rules/branches/main")
    needed = {"CI", CONTEXT}
    gate.require(any(x["type"] == "required_status_checks"
                     and x["parameters"]["strict_required_status_checks_policy"] is True
                     and needed <= {c["context"] for c in x["parameters"]["required_status_checks"]
                                    if c.get("integration_id") == 15368} for x in rules),
                 "protected candidate gate not active")
    gate.require(identity(exact_pr(pr, api=api)) == identity(p), "PR identity changed")
    gate.require(exact_paths(p, pages=pages) == paths, "changed-file evidence moved")
    return {"pr": pr, "head": head, "base": base, "hosted_ready": True,
            "merge_armed": False, "candidate_allocated": False,
            "publication_admission": False}


def published_issue_plan(candidate, ledger, *, requested, api=gate.api, release_gate=gate,
                         verify_bytes=None):
    """Require durable published receipt and a source-bound explicit issue allowlist.

    Returns a read-only plan, never closes an issue. A later reviewed owner
    workflow must re-run this before each idempotent close.
    """
    import base64
    import hashlib
    import json
    import tempfile
    from pathlib import Path
    from gway_remote.android_rc_acceptance import identity as accepted_identity
    from gway_remote.android_rc_promotion import verify_release_asset, PUBLISH_WORKFLOW
    from gway_remote.android_canary_certificate import certificate_sha256

    state = ledger.read(candidate.candidate_id)
    artifact = accepted_identity(ledger, candidate)
    published = state.get("published") or {}
    approval = state.get("approved") or {}
    accepted = state.get("accepted") or {}
    tag = f"android-v{candidate.version_name}"
    gate.require(published.get("tag") == tag
                 and published.get("source_sha") == candidate.source_sha
                 and published.get("apk_sha256") == artifact.apk_sha256
                 and published.get("certificate_sha256") == artifact.certificate_sha256
                 and type(published.get("acceptance_run")) is int
                 and accepted.get("run_id") == published["acceptance_run"]
                 and approved_receipt_matches(approval, published, candidate),
                 "verified publication receipt missing")
    run = api(f"actions/runs/{published['approval_run']}")
    release_gate.verify_run_identity(run, PUBLISH_WORKFLOW, published["approval_run"],
                                    "workflow_dispatch", approval["publication_revision"])
    gate.require(run.get("status") == "completed" and run.get("conclusion") == "success"
                 and run.get("run_attempt") == 1
                 and (run.get("actor") or {}).get("login") == gate.OWNER
                 and (run.get("triggering_actor") or {}).get("login") == gate.OWNER,
                 "publication workflow unverified")
    release = api(f"releases/tags/{tag}")
    verify_release_asset(artifact, release, draft=False, acceptance_run=published["acceptance_run"])
    gate.require(release.get("id") == published.get("release_id")
                 and api(f"commits/{tag}")["sha"] == candidate.source_sha
                 and api(f"git/commits/{candidate.source_sha}")["tree"]["sha"] == candidate.source_tree,
                 "published release identity mismatch")

    def download_verify():
        with tempfile.TemporaryDirectory() as tmp:
            release_gate.gh("release", "download", tag, "-R", gate.REPO,
                            "--pattern", "gway-remote.apk", "--dir", tmp)
            apk = Path(tmp) / "gway-remote.apk"
            gate.require(apk.is_file() and not apk.is_symlink()
                         and 10000 < apk.stat().st_size < 104857600
                         and hashlib.sha256(apk.read_bytes()).hexdigest() == artifact.apk_sha256
                         and certificate_sha256(apk) == artifact.certificate_sha256,
                         "published APK bytes or signer mismatch")
    (verify_bytes or download_verify)()
    row = api(f"contents/docs/android-release-issues.json?ref={candidate.source_sha}")
    gate.require(row.get("encoding") == "base64", "release issue manifest unavailable")
    raw = base64.b64decode(row["content"], validate=False)
    gate.require(0 < len(raw) <= 16384, "invalid release issue manifest")
    manifest = json.loads(raw)
    allowed = manifest.get("issues")
    gate.require(set(manifest) == {"schema", "issues"} and type(manifest["schema"]) is int
                 and manifest["schema"] == 1 and isinstance(allowed, list)
                 and all(type(n) is int and n > 0 and n != 718 for n in allowed)
                 and len(set(allowed)) == len(allowed), "invalid release issue allowlist")
    gate.require(isinstance(requested, list) and requested and len(set(requested)) == len(requested)
                 and all(type(n) is int and n in allowed for n in requested),
                 "unapproved release issue")
    rows = [api(f"issues/{n}") for n in requested]
    gate.require(all("pull_request" not in row and row.get("state") in ("open", "closed")
                     and row.get("number") == n for row, n in zip(rows, requested)),
                 "release issue identity mismatch")
    return {"tag": tag, "source_sha": candidate.source_sha,
            "apk_sha256": artifact.apk_sha256, "release_id": published["release_id"],
            "to_close": [n for n, row in zip(requested, rows) if row["state"] == "open"],
            "already_closed": [n for n, row in zip(requested, rows) if row["state"] == "closed"],
            "mutation_authorized": False}


def approved_receipt_matches(approval, published, candidate):
    return (approval.get("candidate_id") == candidate.candidate_id
            and approval.get("apk_sha256") == published.get("apk_sha256")
            and approval.get("acceptance_run") == published.get("acceptance_run")
            and type(approval.get("approval_run")) is int
            and approval["approval_run"] > 0
            and approval["approval_run"] == published.get("approval_run")
            and bool(gate.SHA.fullmatch(approval.get("publication_revision") or "")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    gate.require(os.environ.get("GITHUB_REPOSITORY") == gate.REPO
                 and args.run_id > 0, "unexpected workflow repository")
    trusted = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    gate.require(gate.SHA.fullmatch(trusted) and gate.api("branches/main")["commit"]["sha"] == trusted,
                 "trusted workflow base moved; reconcile from current main")
    reconcile_all(f"https://github.com/{gate.REPO}/actions/runs/{args.run_id}", trusted_base=trusted)


if __name__ == "__main__":
    main()
