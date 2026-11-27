"""Hermetic candidate-aware readiness tests; no network, devices or release mutations."""
import copy
import unittest
from unittest.mock import Mock
from pathlib import Path

from gway_remote import android_candidate_readiness as r
from gway_remote import android_release_gate as g

HEAD = "a" * 40
BASE = "b" * 40
PR = {"number": 42, "state": "open", "draft": False, "changed_files": 1,
      "base": {"ref": "main", "sha": BASE, "repo": {"full_name": g.REPO}},
      "head": {"sha": HEAD, "repo": {"full_name": g.REPO}}}


class ReadinessTests(unittest.TestCase):
    def test_non_android_and_rename(self):
        self.assertEqual(r.evaluate(PR, {"README.md"}), ("success", "not-applicable"))
        rows = [{"filename": "archive.kt", "previous_filename": "android/app/A.kt", "status": "renamed"}]
        paths = r.exact_paths(PR, pages=lambda _: rows)
        self.assertTrue(g.android_changed(paths))
        for bad in ([], [{"filename": "x", "status": "renamed"}]):
            with self.assertRaises(RuntimeError):
                r.exact_paths(PR, pages=lambda _: bad)

    def test_draft_fork_and_changed_workflow_are_not_ready(self):
        for p, paths in (({**PR, "draft": True}, {"android/A.kt"}),
                         ({**PR, "head": {"sha": HEAD, "repo": {"full_name": "fork/repo"}}}, {"android/A.kt"}),
                         (PR, {"android/A.kt", ".github/workflows/ci.yml"})):
            self.assertEqual(r.evaluate(p, paths)[0], "pending")

    def test_outdated_base_never_ready(self):
        self.assertEqual(r.evaluate(PR, {"android/A.kt"}, api=lambda _: {
            "merge_base_commit": {"sha": HEAD}}), ("pending", "integrate-main"))

    def hosted(self, workflow_id, **changes):
        workflow, job = r.WORKFLOWS[workflow_id]
        return {"id": workflow_id + 1, "workflow_id": workflow_id, "run_number": 2,
                "run_attempt": 1, "path": ".github/workflows/" + workflow,
                "repository": {"full_name": g.REPO}, "head_repository": {"full_name": g.REPO},
                "event": "pull_request", "head_sha": HEAD,
                "pull_requests": [{"number": 42, "head": {"sha": HEAD}, "base": {"sha": BASE}}],
                "status": "completed", "conclusion": "success", **changes}

    def api(self, path):
        if path == f"compare/{BASE}...{HEAD}":
            return {"merge_base_commit": {"sha": BASE}}
        for wid, (_, job) in r.WORKFLOWS.items():
            run = self.hosted(wid)
            if path.startswith(f"actions/workflows/{wid}/"):
                return {"total_count": 1, "workflow_runs": [run]}
            if path == f"actions/runs/{wid+1}":
                return run
            if path == f"actions/runs/{wid+1}/attempts/1/jobs?per_page=100":
                return {"total_count": 1, "jobs": [{"name": job, "conclusion": "success"}]}
        raise AssertionError(path)

    def test_exact_hosted_pass(self):
        self.assertEqual(r.evaluate(PR, {"android/A.kt"}, api=self.api), ("success", "hosted-ready"))

    def test_stale_or_forged_run_not_accepted(self):
        wid = next(iter(r.WORKFLOWS))
        for fields in ({"head_sha": BASE}, {"workflow_id": 1}, {"path": "other.yml"},
                       {"head_repository": {"full_name": "fork/repo"}},
                       {"pull_requests": [{"number": 42, "head": {"sha": HEAD}, "base": {"sha": HEAD}}]}):
            with self.subTest(fields=fields):
                self.assertEqual(r.exact_hosted(PR, wid, api=lambda _: {
                    "total_count": 1, "workflow_runs": [self.hosted(wid, **fields)]}), "pending")

    def test_newest_failure_and_pending_do_not_use_old_success(self):
        wid = next(iter(r.WORKFLOWS))
        for changes, expected in (({"conclusion": "failure"}, "failure"),
                                  ({"status": "in_progress", "conclusion": None}, "pending")):
            rows = [self.hosted(wid), self.hosted(wid, id=999, run_number=3, **changes)]
            self.assertEqual(r.exact_hosted(PR, wid, api=lambda _: {
                "total_count": 2, "workflow_runs": rows}), expected)

    def test_missing_or_failed_required_job(self):
        wid = next(iter(r.WORKFLOWS))
        def api(path):
            if "/jobs?" in path:
                return {"total_count": 1, "jobs": [{"name": "not-required", "conclusion": "success"}]}
            return self.api(path)
        self.assertEqual(r.exact_hosted(PR, wid, api=api), "failure")

    def test_incomplete_listing_fails(self):
        wid = next(iter(r.WORKFLOWS))
        with self.assertRaises(RuntimeError):
            r.exact_hosted(PR, wid, api=lambda _: {"total_count": 2, "workflow_runs": [self.hosted(wid)]})

    def test_reconcile_rechecks_pr_before_success(self):
        p = copy.deepcopy(PR)
        def api(path):
            if path == "pulls/42":
                return copy.deepcopy(p)
            return {"commit": {"sha": BASE}}
        calls = []
        def pages(_):
            p["head"]["sha"] = BASE
            return [{"filename": "README.md", "status": "modified"}]
        with self.assertRaises(RuntimeError):
            r.reconcile(42, "url", api=api, pages=pages, write=lambda *a: calls.append(a))
        self.assertEqual([c[2] for c in calls], ["pending"])

    def test_incomplete_paths_report_failure(self):
        api = lambda path: PR if path == "pulls/42" else {"commit": {"sha": BASE}}
        write = Mock()
        with self.assertRaises(RuntimeError):
            r.reconcile(42, "url", api=api, pages=lambda _: [], write=write)
        self.assertEqual([c.args[2] for c in write.call_args_list], ["pending", "failure"])

    def test_workflow_read_only_except_status(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / ".github/workflows/android-candidate-readiness.yml").read_text()
        for marker in ("pull_request_target:", "workflow_run:", "push:", "statuses: write",
                       "persist-credentials: false", "github.event.pull_request.base.sha || github.sha",
                       "cancel-in-progress: false"):
            self.assertIn(marker, workflow)
        for marker in ("self-hosted", "contents: write", "actions: write", "secrets.",
                       "pull-requests: write", "github.event.pull_request.head.sha"):
            self.assertNotIn(marker, workflow)


    def test_ruleset_plan_preserves_all_existing_protections(self):
        old = {"name": "main", "target": "branch", "enforcement": "active",
               "bypass_actors": [], "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
               "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}, {"type": "pull_request"},
                         {"type": "required_status_checks", "parameters": {
                             "strict_required_status_checks_policy": True,
                             "required_status_checks": [{"context": "CI", "integration_id": 15368}]}}]}
        original = copy.deepcopy(old)
        planned = r.ruleset_plan(old)
        self.assertEqual(old, original)
        self.assertEqual(planned["rules"][:-1], old["rules"][:-1])
        self.assertEqual(planned["rules"][-1]["parameters"]["required_status_checks"][-1],
                         {"context": r.CONTEXT, "integration_id": 15368})
        self.assertEqual(r.ruleset_plan(planned), planned)
        with self.assertRaises(RuntimeError):
            r.ruleset_plan({**old, "bypass_actors": [{"actor_id": 1}]})

    def test_merge_plan_requires_owner_exact_base_and_active_rules(self):
        p = {**PR, "user": {"login": g.OWNER}}
        def api(path):
            if path == "pulls/42":
                return p
            if path == "branches/main":
                return {"commit": {"sha": BASE}}
            if path == "rules/branches/main":
                return [{"type": "required_status_checks", "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [{"context": k, "integration_id": 15368}
                                               for k in ("CI", r.CONTEXT)]}}]
            return self.api(path)
        rows = lambda _: [{"filename": "android/A.kt", "status": "modified"}]
        for opt_in, actor, head in ((False, g.OWNER, HEAD), (True, "other", HEAD), (True, g.OWNER, BASE)):
            with self.assertRaises(RuntimeError):
                r.merge_plan(42, head, BASE, owner_opt_in=opt_in, actor=actor, api=api, pages=rows)
        with self.assertRaises(RuntimeError):
            r.merge_plan(42, HEAD, BASE, owner_opt_in=True, actor=g.OWNER,
                         api=lambda path: [] if path == "rules/branches/main" else api(path), pages=rows)
        plan = r.merge_plan(42, HEAD, BASE, owner_opt_in=True, actor=g.OWNER, api=api, pages=rows)
        self.assertTrue(plan["hosted_ready"])
        self.assertFalse(plan["merge_armed"])
        self.assertFalse(plan["candidate_allocated"])
        self.assertFalse(plan["publication_admission"])



    def test_trusted_workflow_base_must_still_match(self):
        api = lambda path: PR if path == "pulls/42" else {"commit": {"sha": BASE}}
        write = Mock()
        with self.assertRaises(RuntimeError):
            r.reconcile(42, "url", trusted_base=HEAD, api=api, pages=lambda _: [], write=write)
        write.assert_not_called()

    def test_published_issue_plan_only_after_verified_release(self):
        import base64
        import json
        from gway_remote.android_release_candidate import Candidate, SignedArtifact
        from gway_remote.android_rc_acceptance import full_receipt, smoke_receipt, SMOKE_CHECKS
        from gway_remote.android_rc_contracts import GROUPS
        candidate = Candidate(HEAD, BASE, 801, "0.2.801")
        digest, cert = "c" * 64, "d" * 64
        artifact = SignedArtifact(candidate, digest, cert, 2, 3)
        hosted = {"ci_run": 10, "compose_run": 11, "build_run": 12,
                  "contract_artifact_id": 13, "hosted_groups": dict.fromkeys(GROUPS, "pass")}
        accepted = full_receipt(artifact, 14, smoke_receipt(artifact, 14, dict.fromkeys(SMOKE_CHECKS, "pass")), hosted)
        tag = "android-v0.2.801"
        approval = {"candidate_id": candidate.candidate_id, "apk_sha256": digest,
                    "acceptance_run": 14, "publication_revision": HEAD, "approval_run": 15}
        published = {"tag": tag, "source_sha": HEAD, "apk_sha256": digest,
                     "certificate_sha256": cert, "acceptance_run": 14, "approval_run": 15,
                     "release_id": 16}
        ledger = Mock()
        ledger.read.return_value = {"signed": {"apk_sha256": digest, "certificate_sha256": cert,
                                              "artifact_id": 2, "run_id": 3},
                                    "accepted": accepted, "approved": approval, "published": published}
        ledger.consecutive_upgrade_health.return_value = {"ok": True}
        release = {"tag_name": tag, "target_commitish": HEAD, "draft": False, "prerelease": False, "id": 16,
                   "assets": [{"name": "gway-remote.apk", "state": "uploaded", "digest": "sha256:" + digest}],
                   "body": f"Android-Version-Code: 801\nSource-Commit: {HEAD}\nAPK-SHA256: {digest}\nAcceptance-Run: 14\n"}
        rows = {"actions/runs/15": {"status": "completed", "conclusion": "success", "run_attempt": 1,
                                   "actor": {"login": g.OWNER}, "triggering_actor": {"login": g.OWNER},
                                   "display_title": f"Promote RC 801 {digest} acceptance 14"},
                f"releases/tags/{tag}": release, f"commits/{tag}": {"sha": HEAD},
                f"git/commits/{HEAD}": {"tree": {"sha": BASE}},
                f"contents/docs/android-release-issues.json?ref={HEAD}": {
                    "encoding": "base64", "content": base64.b64encode(json.dumps({"schema": 1, "issues": [711, 746]}).encode()).decode()},
                "issues/711": {"number": 711, "state": "open"},
                "issues/746": {"number": 746, "state": "closed"}}
        release_gate = Mock()
        verify = Mock()
        def plan(requested):
            return r.published_issue_plan(candidate, ledger, requested=requested, api=rows.__getitem__,
                                          release_gate=release_gate, verify_bytes=verify)
        result = plan([711, 746])
        self.assertEqual(result["to_close"], [711])
        self.assertEqual(result["already_closed"], [746])
        self.assertFalse(result["mutation_authorized"])
        release_gate.gh.assert_not_called()
        for ids in ([718], [711, 711], [999]):
            with self.assertRaises(RuntimeError):
                plan(ids)
        release["draft"] = True
        with self.assertRaises(ValueError):
            plan([711])
        release["draft"] = False
        ledger.read.return_value["published"] = None
        with self.assertRaises(RuntimeError):
            plan([711])
        release_gate.gh.assert_not_called()



if __name__ == "__main__":
    unittest.main()
