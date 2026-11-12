"""Offline admission/runner contract tests. Never contact gway-001 or GitHub."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts" / "auto-deploy-ocpp-simulator.py"
spec = importlib.util.spec_from_file_location("sim_auto_install", SOURCE)
assert spec and spec.loader
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)
SHA = "a" * 40
OLD = "b" * 40


def ci(run_number=1, attempt=1, status="completed", conclusion="success", sha=SHA):
    return {"head_sha": sha, "event": "push", "head_branch": "main",
            "run_number": run_number, "run_attempt": attempt,
            "status": status, "conclusion": conclusion}


@pytest.mark.parametrize("value", [None, "", "a" * 39, "Z" * 40, "b" * 41])
def test_invalid_sha_fails_closed(value):
    with pytest.raises(sim.AdmissionError):
        sim.require_sha(value)


def test_ci_requires_exact_main_push_and_latest_success():
    assert sim.verified_ci({"workflow_runs": [ci()]}, SHA)
    assert not sim.verified_ci({"workflow_runs": [ci(sha=OLD)]}, SHA)
    assert not sim.verified_ci({"workflow_runs": [{**ci(), "event": "pull_request"}]}, SHA)
    assert not sim.verified_ci({"workflow_runs": [{**ci(), "head_branch": "draft"}]}, SHA)
    assert not sim.verified_ci({"workflow_runs": []}, SHA)
    assert not sim.verified_ci({"workflow_runs": [ci(), ci(2, conclusion="failure")]}, SHA)
    assert not sim.verified_ci({"workflow_runs": [ci(), ci(2, status="in_progress", conclusion=None)]}, SHA)
    assert sim.verified_ci({"workflow_runs": [ci(), ci(2, attempt=2)]}, SHA)
    with pytest.raises(sim.AdmissionError):
        sim.verified_ci({"bad": []}, SHA)


def test_pr_not_merged_never_fetches_main_or_starts_install(monkeypatch):
    monkeypatch.setattr(sim, "preflight", lambda: None)
    calls = []
    def github(path):
        calls.append(path)
        if path == "repos/arthexis/ocpp-simulator/pulls/20":
            return {"merged": False}
        raise AssertionError("unexpected main or CI query before PR merge")
    monkeypatch.setattr(sim, "github", github)
    monkeypatch.setattr(sim, "invoke", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("no subprocess is allowed before the merge")))
    assert sim.auto_install().startswith("SKIPPED")
    assert calls == ["repos/arthexis/ocpp-simulator/pulls/20"]


def test_pending_exact_ci_does_not_use_checkout_or_installer(monkeypatch):
    monkeypatch.setattr(sim, "preflight", lambda: None)
    def github(path):
        if path.endswith("/pulls/20"):
            return {"merged": True}
        if path.endswith("/branches/main"):
            return {"commit": {"sha": SHA}}
        return {"workflow_runs": [ci(status="in_progress", conclusion=None)]}
    monkeypatch.setattr(sim, "github", github)
    monkeypatch.setattr(sim, "invoke", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("CI not accepted; no checkout/build")))
    assert sim.auto_install().startswith("SKIPPED")


def test_pointer_must_be_symlink(tmp_path):
    path = tmp_path / "current"
    assert sim.read_pointer(path) == ""
    path.write_text("unexpected")
    with pytest.raises(sim.AdmissionError, match="non-symlink"):
        sim.read_pointer(path)
    path.unlink()
    path.symlink_to(tmp_path / "releases" / SHA)
    assert sim.read_pointer(path).endswith(SHA)


def test_workflow_uses_only_existing_gway_remote_runner():
    workflow = (ROOT / ".github/workflows/ocpp-simulator-deploy.yml").read_text()
    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "runs-on: [self-hosted, Linux, ARM64, gway-001]" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "python3 scripts/auto-deploy-ocpp-simulator.py" in workflow
    assert "sudo" not in workflow and "secrets." not in workflow
    assert "persist-credentials: false" in workflow


def test_fixed_repository_and_no_new_token_or_service():
    content = SOURCE.read_text()
    assert 'REPOSITORY = "arthexis/ocpp-simulator"' in content
    assert 'PR_NUMBER = 20' in content
    assert 'OCPP_SIMULATOR_EXPECTED_MAIN_SHA' in content
    assert "credential.helper=!gh auth git-credential" in content
    assert "TemporaryDirectory(" in content
    assert "clone" in content and "--no-checkout" in content
    assert "verify_installed(" in content
    assert '"sh", "./deploy.sh"' in content
    assert "subprocess.Popen" not in content
    assert "systemctl" not in content
    assert "sudo" not in content
