import pytest

from gway_remote import android_release_gate as gate
from gway_remote import android_release_close as release

SHA = "a" * 40
BASE = "b" * 40
DIGEST = "c" * 64


def test_conditional_paths_and_rename():
    assert gate.android_changed(["android/app/src/Test.kt"])
    assert gate.android_changed([".github/workflows/android-compose-ui.yml"])
    assert not gate.android_changed(["gway_remote/mobile.py", "README.md"])


def test_explicit_release_links_and_closing_keywords():
    assert gate.release_issues("Release-Issue: #746\nRelease-Issue: #746\n") == [746]
    for body in ("Closes #746", "Fixes arthexis/gway-remote#746", "Resolves https://github.com/arthexis/gway-remote/issues/746"):
        with pytest.raises(RuntimeError):
            gate.release_issues(body)


def test_receipt_fail_closed():
    good = {"pr": 747, "source_sha": SHA, "run_id": 123, "install_run_id": 456,
            "suite": "baseline", "status": "passed", "tests_passed": 8,
            "production_package_unchanged": True}
    gate.verify_receipt(good, 747, SHA, 123, 456, 8)
    for k, v in {"source_sha": BASE, "run_id": 999, "install_run_id": 999,
                 "suite": "other", "status": "failed", "tests_passed": 7,
                 "production_package_unchanged": False}.items():
        with pytest.raises(RuntimeError):
            gate.verify_receipt({**good, k: v}, 747, SHA, 123, 456, 8)


def test_release_fail_closed():
    tag = "android-v0.2.123"
    good = {"tag_name": tag, "target_commitish": SHA, "draft": False, "prerelease": False,
            "body": f"Source-Commit: {SHA}\nAPK-SHA256: {DIGEST}\n",
            "assets": [{"name": "gway-remote.apk", "state": "uploaded",
                        "size": 50000, "digest": "sha256:" + DIGEST}]}
    release.verify_release(good, SHA, tag, SHA, DIGEST)
    for change in ({"target_commitish": BASE}, {"draft": True}, {"assets": []},
                   {"body": ""}, {"assets": [{**good["assets"][0], "digest": "sha256:" + "d"*64}]}):
        with pytest.raises(RuntimeError):
            release.verify_release({**good, **change}, SHA, tag, SHA, DIGEST)
    with pytest.raises(RuntimeError):
        release.verify_release(good, BASE, tag, SHA, DIGEST)


def test_conditional_reports_for_non_android_and_refuses_stale(monkeypatch):
    p = {"head": {"sha": SHA}, "base": {"ref": "main"}}
    monkeypatch.setattr(gate, "api", lambda _: p)
    monkeypatch.setattr(gate, "changed", lambda _: {"README.md"})
    statuses = []
    monkeypatch.setattr(gate, "status", lambda *args: statuses.append(args))
    gate.conditional(747, SHA, "https://example.test")
    assert statuses[-1][1] == "success"
    monkeypatch.setattr(gate, "changed", lambda _: {"android/app/build.gradle.kts"})
    gate.conditional(747, SHA, "https://example.test")
    assert statuses[-1][1] == "pending"
    with pytest.raises(RuntimeError):
        gate.conditional(747, BASE, "https://example.test")


def test_current_rejects_changed_head_or_base(monkeypatch):
    p = {"state": "open", "draft": False, "base": {"ref": "main", "sha": BASE},
         "head": {"sha": SHA, "repo": {"full_name": gate.REPO}}}
    monkeypatch.setattr(gate, "api", lambda path: p if path.startswith("pulls/") else {"commit": {"sha": BASE}})
    assert gate.current(747, SHA, BASE) == p
    with pytest.raises(RuntimeError):
        gate.current(747, BASE, BASE)
    with pytest.raises(RuntimeError):
        gate.current(747, SHA, SHA)


def test_acceptance_failure_never_merges(monkeypatch):
    monkeypatch.setattr(gate, "current", lambda *a: {"user": {"login": gate.OWNER}})
    monkeypatch.setattr(gate, "changed", lambda _: {"android/app/build.gradle.kts"})
    monkeypatch.setattr(gate, "api", lambda _: {"merge_base_commit": {"sha": BASE}})
    monkeypatch.setattr(gate, "issue_links", lambda *a: [])
    monkeypatch.setattr(gate, "assert_gate_required", lambda: None)
    statuses = []
    monkeypatch.setattr(gate, "status", lambda *args: statuses.append(args))
    monkeypatch.setattr(gate, "pr_ci", lambda *a: gate.require(False, "failed CI"))
    monkeypatch.setattr(gate, "gh", lambda *a: pytest.fail("unexpected mutation"))
    with pytest.raises(RuntimeError, match="failed CI"):
        gate.accept(747, SHA, BASE, "no", 123, True, 8, "https://example.test")
    assert [s[1] for s in statuses] == ["pending", "failure"]


def test_rule_plan_only_adds_gate():
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
    with pytest.raises(RuntimeError):
        updated_ruleset({**old, "bypass_actors": [{"actor_id": 1}]})


def test_release_closure_only_after_verified_asset(tmp_path, monkeypatch):
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
    monkeypatch.setattr(release, "api", values.__getitem__)
    calls = []
    monkeypatch.setattr(release, "gh", lambda *args: calls.append(args))
    metadata["assets"][0]["digest"] = "sha256:" + DIGEST
    with pytest.raises(RuntimeError):
        release.close(tag, SHA, apk)
    assert not calls
    metadata["assets"][0]["digest"] = "sha256:" + digest
    pr["body"] = "Release-Issue: #999"
    with pytest.raises(RuntimeError):
        release.close(tag, SHA, apk)
    assert not calls
    pr["body"] = "Release-Issue: #746"
    release.close(tag, SHA, apk)
    assert calls[0][:3] == ("issue", "close", "746")
    values["issues/746"]["state"] = "closed"
    release.close(tag, SHA, apk)
    assert len(calls) == 1
