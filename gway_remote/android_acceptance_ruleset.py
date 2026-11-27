"""Staged opt-in ruleset activation; no bypasses or replacement protections."""
import argparse
import copy
import json
import re
import subprocess

from gway_remote.android_release_gate import CONTEXT, REPO, api, changed, android_changed, dispatch, wait_run, require


def updated_ruleset(rule):
    fields = ("name", "target", "enforcement", "bypass_actors", "conditions", "rules")
    value = copy.deepcopy({k: rule[k] for k in fields})
    require(value["name"] == "main" and value["target"] == "branch"
            and value["enforcement"] == "active" and not value["bypass_actors"],
            "unexpected existing ruleset; do not modify")
    rules = [r for r in value["rules"] if r["type"] == "required_status_checks"]
    require(len(rules) == 1, "ambiguous required checks rule")
    params = rules[0]["parameters"]
    checks = params["required_status_checks"]
    require(params["strict_required_status_checks_policy"]
            and any(c["context"] == "CI" and c.get("integration_id") == 15368 for c in checks),
            "existing strict CI protection missing")
    existing = [c for c in checks if c["context"] == CONTEXT]
    require(not existing or existing == [{"context": CONTEXT, "integration_id": 15368}],
            "unexpected gate integration")
    if not existing:
        checks.append({"context": CONTEXT, "integration_id": 15368})
    return value


def backfill():
    api("contents/.github/workflows/android-acceptance.yml?ref=main")
    prs = api("pulls?state=open&base=main&per_page=100")
    require(len(prs) < 100, "too many PRs for bounded backfill")
    for p in prs:
        run = dispatch("android-acceptance.yml", mode="classify", pr_number=str(p["number"]),
                       expected_sha=p["head"]["sha"], expected_base=p["base"]["sha"],
                       auto_merge="false", canary_reset="no")
        wait_run("android-acceptance.yml", run, "workflow_dispatch", timeout=300)


def preflight():
    # All open PR heads must have a classification from trusted Actions before enforcement.
    prs = api("pulls?state=open&base=main&per_page=100")
    require(len(prs) < 100, "too many PRs for bounded activation")
    for p in prs:
        sha = p["head"]["sha"]
        latest = api(f"commits/{sha}/status")["statuses"]
        combined = [s for s in latest if s["context"] == CONTEXT]
        require(len(combined) == 1, f"missing current classification for PR {p['number']}")
        statuses = api(f"commits/{sha}/statuses?per_page=100")
        matches = [s for s in statuses if s["context"] == CONTEXT and s["id"] == combined[0]["id"]]
        require(len(matches) == 1, f"missing classification for PR {p['number']}")
        s = matches[0]
        m = re.fullmatch(r"https://github.com/arthexis/gway-remote/actions/runs/(\d+)", s.get("target_url") or "")
        require(m and (s.get("creator") or {}).get("login") == "github-actions[bot]", "untrusted status")
        r = api(f"actions/runs/{m.group(1)}")
        require(r["path"] == ".github/workflows/android-acceptance.yml"
                and r["event"] in ("pull_request_target", "workflow_dispatch")
                and r["conclusion"] == "success", "classification not verified")
        require(android_changed(changed(p["number"])) or s["state"] == "success",
                "backend-only PR blocked")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ruleset", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backfill", action="store_true")
    args = parser.parse_args()
    path = f"rulesets/{args.ruleset}"
    old = api(path)
    new = updated_ruleset(old)
    print(json.dumps(new, indent=2))
    if args.backfill:
        backfill()
    if args.apply:
        preflight()
        require(api(path) == old, "ruleset changed concurrently")
        subprocess.run(["gh", "api", f"repos/{REPO}/{path}", "--method", "PUT", "--input", "-"],
                       input=json.dumps(new), text=True, check=True, timeout=90, stdout=subprocess.DEVNULL)
        require(updated_ruleset(api(path)) == new, "ruleset readback mismatch")
        checks = [c for r in api("rules/branches/main") if r["type"] == "required_status_checks"
                  for c in r["parameters"]["required_status_checks"]]
        require({"context": CONTEXT, "integration_id": 15368} in checks, "gate not enforced")
        print("Gate active; existing rules preserved")


if __name__ == "__main__":
    main()
