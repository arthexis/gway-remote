"""Offline end-to-end receipt tests for the fixed gway-001 workflow script.

All external commands are intercepted. The production script's fixed user and
checkout paths are substituted only in the copied test fixture.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "scripts/deploy-webos-tv.sh"
SHA = "a" * 40
OTHER = "b" * 40


def executable(path, contents):
    path.write_text("#!/bin/sh\nset -eu\n" + contents)
    path.chmod(0o755)


def fixture(tmp_path):
    checkout = tmp_path / "trusted-checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "scripts").mkdir()
    state = tmp_path / "state"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    source = SOURCE.read_text()
    assert 'checkout="/home/arthe/Repos/gway-webos-tv"' in source
    assert 'state_dir="/home/arthe/.local/state/gway-webos-tv"' in source
    source = source.replace('checkout="/home/arthe/Repos/gway-webos-tv"',
                            f'checkout="{checkout}"')
    source = source.replace('state_dir="/home/arthe/.local/state/gway-webos-tv"',
                            f'state_dir="{state}"')
    script = tmp_path / "orchestrate.sh"
    script.write_text(source)
    script.chmod(0o755)
    executable(bindir / "id", 'if [ "$1" = "-un" ]; then echo arthe; else exit 3; fi\n')
    executable(bindir / "gh", """case "$*" in
  *"branches/main"*) echo "$MOCK_MAIN_SHA";;
  *"actions/workflows/tests.yml/runs"*) echo "$MOCK_CI_STATE";;
  *) echo "Unexpected gh call" >&2; exit 3;;
esac
""")
    executable(bindir / "git", """case "$*" in
  *"status --porcelain") :;;
  *"fetch --quiet origin main") :;;
  *"rev-parse refs/remotes/origin/main") echo "$MOCK_MAIN_SHA";;
  *"switch main") :;;
  *"merge --ff-only"*) :;;
  *"rev-parse HEAD") echo "$MOCK_MAIN_SHA";;
  *) echo "Unexpected git call: $*" >&2; exit 3;;
esac
""")
    executable(checkout / "deploy.sh",
               'printf "node:%s\\n" "$GWAY_WEBOS_EXPECTED_SHA" >> "$MOCK_CALLS"\n')
    executable(bindir / "python3",
               'printf "tv:%s\\n" "$*" >> "$MOCK_CALLS"\nexit "$MOCK_TV_EXIT"\n')
    env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ["PATH"],
               MOCK_MAIN_SHA=SHA, MOCK_CI_STATE="completed:success",
               MOCK_TV_EXIT="10", MOCK_CALLS=str(tmp_path / "calls"))
    return script, state, env


def run(script, env):
    return subprocess.run(["bash", str(script)], env=env, text=True, capture_output=True)



class WebOSDeployScriptTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="webos-script-")
        self.temp_path = Path(self._temporary.name)

    def tearDown(self):
        self._temporary.cleanup()

    def test_offline_defer_does_not_set_tv_receipt_and_recovers_without_new_commit(self):
        tmp_path = self.temp_path
        script, state, env = fixture(tmp_path)
        state.mkdir()
        (state / "auto-deployed-sha").write_text(SHA + "\n")  # Old misleading receipt.
        result = run(script, env)
        assert result.returncode == 0, result.stderr
        assert "TV offline" in result.stdout
        assert not (state / "tv-installed-sha").exists()
        assert (tmp_path / "calls").read_text().splitlines() == [
            "node:" + SHA, "tv:scripts/auto-tv-deploy.py --require-online"]
        env["MOCK_TV_EXIT"] = "0"
        result = run(script, env)
        assert result.returncode == 0, result.stderr
        assert (state / "tv-installed-sha").read_text().strip() == SHA
        result = run(script, env)
        assert result.returncode == 0, result.stderr
        calls = (tmp_path / "calls").read_text().splitlines()
        assert calls.count("node:" + SHA) == 3
        assert calls.count("tv:scripts/auto-tv-deploy.py --require-online") == 2
    
    
    def test_real_tv_failure_does_not_claim_receipt(self):
        tmp_path = self.temp_path
        script, state, env = fixture(tmp_path)
        env["MOCK_TV_EXIT"] = "1"
        result = run(script, env)
        assert result.returncode == 1
        assert "TV installation failed" in result.stdout
        assert not (state / "tv-installed-sha").exists()
    
    
    def test_missing_or_failed_exact_sha_ci_never_runs_any_deployment(self):
        tmp_path = self.temp_path
        script, state, env = fixture(tmp_path)
        env["MOCK_CI_STATE"] = "completed:failure"
        result = run(script, env)
        assert result.returncode == 0
        assert "CI not successful" in result.stdout
        assert not state.exists()
        assert not (tmp_path / "calls").exists()
    