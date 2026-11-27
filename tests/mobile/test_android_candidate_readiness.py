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


if __name__ == "__main__":
    unittest.main()
