import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from gway_remote import android_release_gate as gate
from gway_remote import android_release_close as release

SHA = "a" * 40
BASE = "b" * 40
DIGEST = "c" * 64


class AndroidReleaseGateTests(unittest.TestCase):
    def replace(self, obj, name, value):
        self.enterContext(patch.object(obj, name, value))

    def test_conditional_paths_and_rename(self):
        assert gate.android_changed(["android/app/src/Test.kt"])
        assert gate.android_changed([".github/workflows/android-compose-ui.yml"])
        assert not gate.android_changed(["gway_remote/mobile.py", "README.md"])


    def test_explicit_release_links_and_closing_keywords(self):
        assert gate.release_issues("Release-Issue: #746\nRelease-Issue: #746\n") == [746]
        for body in ("Closes #746", "Fixes arthexis/gway-remote#746", "Resolves https://github.com/arthexis/gway-remote/issues/746"):
            with self.assertRaises(RuntimeError):
                gate.release_issues(body)


    def test_receipt_fail_closed(self):
        good = {"pr": 747, "source_sha": SHA, "run_id": 123, "install_run_id": 456,
                "suite": "baseline", "status": "passed", "tests_passed": 8,
                "production_package_unchanged": True}
        gate.verify_receipt(good, 747, SHA, 123, 456, 8)
        for k, v in {"source_sha": BASE, "run_id": 999, "install_run_id": 999,
                     "suite": "other", "status": "failed", "tests_passed": 7,
                     "production_package_unchanged": False}.items():
            with self.assertRaises(RuntimeError):
                gate.verify_receipt({**good, k: v}, 747, SHA, 123, 456, 8)


    def test_release_fail_closed(self):
        tag = "android-v0.2.123"
        good = {"tag_name": tag, "target_commitish": SHA, "draft": False, "prerelease": False,
                "body": f"Source-Commit: {SHA}\nAPK-SHA256: {DIGEST}\n",
                "assets": [{"name": "gway-remote.apk", "state": "uploaded",
                            "size": 50000, "digest": "sha256:" + DIGEST}]}
        release.verify_release(good, SHA, tag, SHA, DIGEST)
        for change in ({"target_commitish": BASE}, {"draft": True}, {"assets": []},
                       {"body": ""}, {"assets": [{**good["assets"][0], "digest": "sha256:" + "d"*64}]}):
            with self.assertRaises(RuntimeError):
                release.verify_release({**good, **change}, SHA, tag, SHA, DIGEST)
        with self.assertRaises(RuntimeError):
            release.verify_release(good, BASE, tag, SHA, DIGEST)


    def test_conditional_reports_for_non_android_and_refuses_stale(self):
        p = {"head": {"sha": SHA}, "base": {"ref": "main"}}
        self.replace(gate, "api", lambda _: p)
        self.replace(gate, "changed", lambda _: {"README.md"})
        statuses = []
        self.replace(gate, "status", lambda *args: statuses.append(args))
        gate.conditional(747, SHA, "https://example.test")
        assert statuses[-1][1] == "success"
        self.replace(gate, "changed", lambda _: {"android/app/build.gradle.kts"})
        gate.conditional(747, SHA, "https://example.test")
        assert statuses[-1][1] == "pending"
        with self.assertRaises(RuntimeError):
            gate.conditional(747, BASE, "https://example.test")


    def test_current_rejects_changed_head_or_base(self):
        p = {"state": "open", "draft": False, "base": {"ref": "main", "sha": BASE},
             "head": {"sha": SHA, "repo": {"full_name": gate.REPO}}}
        self.replace(gate, "api", lambda path: p if path.startswith("pulls/") else {"commit": {"sha": BASE}})
        assert gate.current(747, SHA, BASE) == p
        with self.assertRaises(RuntimeError):
            gate.current(747, BASE, BASE)
        with self.assertRaises(RuntimeError):
            gate.current(747, SHA, SHA)


    def test_acceptance_failure_never_merges(self):
        self.replace(gate, "current", lambda *a: {"user": {"login": gate.OWNER}})
        self.replace(gate, "changed", lambda _: {"android/app/build.gradle.kts"})
        self.replace(gate, "api", lambda _: {"merge_base_commit": {"sha": BASE}})
        self.replace(gate, "issue_links", lambda *a: [])
        self.replace(gate, "assert_gate_required", lambda: None)
        self.replace(gate, "assert_publication_ready", lambda: None)
        statuses = []
        self.replace(gate, "status", lambda *args: statuses.append(args))
        self.replace(gate, "pr_ci", lambda *a: gate.require(False, "failed CI"))
        self.replace(gate, "gh", lambda *a: self.fail("unexpected mutation"))
        with self.assertRaisesRegex(RuntimeError, "failed CI"):
            gate.accept(747, SHA, BASE, "no", 123, True, 8, "https://example.test")
        assert [s[1] for s in statuses] == ["pending", "failure"]


    def test_rule_plan_only_adds_gate(self):
        from gway_remote.android_acceptance_ruleset import updated_ruleset
        old = {"name": "main", "target": "branch", "enforcement": "active",
               "bypass_actors": [], "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
               "rules": [{"type": "deletion"}, {"type": "required_status_checks", "parameters": {
                   "strict_required_status_checks_policy": True,
                   "required_status_checks": [{"context": "CI", "integration_id": 15368}]}}]}
        new = updated_ruleset(old)
        assert new["rules"][0] == old["rules"][0]
        assert new["conditions"] == old["conditions"]
        assert len(old["rules"][1]["parameters"]["required_status_checks"]) == 1
        assert new["rules"][1]["parameters"]["required_status_checks"][-1] == {
            "context": gate.CONTEXT, "integration_id": 15368}
        assert updated_ruleset(new) == new
        with self.assertRaises(RuntimeError):
            updated_ruleset({**old, "bypass_actors": [{"actor_id": 1}]})


    def test_release_closure_only_after_verified_asset(self):
        tmp_path = Path(self.enterContext(tempfile.TemporaryDirectory()))
        import hashlib
        apk = tmp_path / "gway-remote.apk"
        apk.write_bytes(b"x" * 20000)
        digest = hashlib.sha256(apk.read_bytes()).hexdigest()
        tag = "android-v0.2.123"
        metadata = {"tag_name": tag, "target_commitish": SHA, "draft": False, "prerelease": False,
                    "html_url": "https://github.com/arthexis/gway-remote/releases/tag/" + tag,
                    "body": f"Source-Commit: {SHA}\nAPK-SHA256: {digest}\n",
                    "assets": [{"name": "gway-remote.apk", "state": "uploaded",
                                "size": 20000, "digest": "sha256:" + digest}]}
        pr = {"merge_commit_sha": SHA, "merged_at": "today", "base": {"ref": "main"},
              "user": {"login": gate.OWNER}, "head": {"repo": {"full_name": gate.REPO}},
              "body": "Release-Issue: #746"}
        values = {f"releases/tags/{tag}": metadata, f"commits/{tag}": {"sha": SHA},
                  f"commits/{SHA}/pulls?per_page=100": [pr],
                  f"commits/{SHA}": {"commit": {"message": "Release-Issue: #746"}},
                  "issues/746": {"state": "open"}}
        self.replace(release, "api", values.__getitem__)
        calls = []
        self.replace(release, "gh", lambda *args: calls.append(args))
        metadata["assets"][0]["digest"] = "sha256:" + DIGEST
        with self.assertRaises(RuntimeError):
            release.close(tag, SHA, apk)
        assert not calls
        metadata["assets"][0]["digest"] = "sha256:" + digest
        pr["body"] = "Release-Issue: #999"
        with self.assertRaises(RuntimeError):
            release.close(tag, SHA, apk)
        assert not calls
        pr["body"] = "Release-Issue: #746"
        release.close(tag, SHA, apk)
        assert calls[0][:3] == ("issue", "close", "746")
        values["issues/746"]["state"] = "closed"
        release.close(tag, SHA, apk)
        assert len(calls) == 1

    def test_staged_publication_hold_blocks_auto_merge(self):
        import base64
        self.replace(gate, "api", lambda _: {"encoding": "base64",
                     "content": base64.b64encode(b"# ANDROID_PUBLICATION_HOLD_718").decode()})
        with self.assertRaisesRegex(RuntimeError, "publication suspended"):
            gate.assert_publication_ready()

    def test_dispatched_run_retries_initial_404_only(self):
        import subprocess
        from unittest.mock import Mock
        missing = subprocess.CalledProcessError(1, ["gh"], stderr="gh: Not Found (HTTP 404)")
        run = {"path": ".github/workflows/android-canary.yml", "event": "workflow_dispatch",
               "head_branch": "main", "status": "completed", "conclusion": "success"}
        api = Mock(side_effect=[missing, missing, run])
        self.replace(gate, "api", api)
        self.replace(gate.time, "sleep", lambda _: None)
        self.assertEqual(gate.wait_run("android-canary.yml", 123, "workflow_dispatch"), run)
        self.assertEqual([c.args for c in api.call_args_list], [("actions/runs/123",)] * 3)

    def test_run_does_not_retry_auth_denial_or_wrong_identity(self):
        import subprocess
        from unittest.mock import Mock
        denied = subprocess.CalledProcessError(1, ["gh"], stderr="gh: Forbidden (HTTP 403)")
        api = Mock(side_effect=denied)
        self.replace(gate, "api", api)
        with self.assertRaises(subprocess.CalledProcessError):
            gate.wait_run("android-canary.yml", 123, "workflow_dispatch")
        api.assert_called_once()
        api.side_effect = None
        api.return_value = {"path": ".github/workflows/other.yml", "event": "workflow_dispatch"}
        with self.assertRaisesRegex(RuntimeError, "unexpected workflow identity"):
            gate.wait_run("android-canary.yml", 123, "workflow_dispatch")

    def test_dispatched_run_missing_retry_is_bounded(self):
        import subprocess
        from unittest.mock import Mock
        api = Mock(side_effect=subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 404"))
        self.replace(gate, "api", api)
        self.replace(gate.time, "sleep", lambda _: None)
        with self.assertRaises(subprocess.CalledProcessError):
            gate.wait_run("android-canary.yml", 123, "workflow_dispatch")
        self.assertEqual(api.call_count, 9)
