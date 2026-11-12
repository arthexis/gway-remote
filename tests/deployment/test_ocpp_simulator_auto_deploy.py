"""Offline unittest contracts; never contact GitHub, runner or production."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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


class SimulatorAutoDeployTests(unittest.TestCase):
    def test_invalid_sha_fails_closed(self):
        for value in (None, "", "a" * 39, "Z" * 40, "b" * 41):
            with self.subTest(value=value), self.assertRaises(sim.AdmissionError):
                sim.require_sha(value)

    def test_ci_requires_exact_main_push_and_latest_success(self):
        self.assertTrue(sim.verified_ci({"workflow_runs": [ci()]}, SHA))
        bad = [
            [ci(sha=OLD)],
            [{**ci(), "event": "pull_request"}],
            [{**ci(), "head_branch": "draft"}],
            [],
            [ci(), ci(2, conclusion="failure")],
            [ci(), ci(2, status="in_progress", conclusion=None)],
        ]
        for runs in bad:
            with self.subTest(runs=runs):
                self.assertFalse(sim.verified_ci({"workflow_runs": runs}, SHA))
        self.assertTrue(sim.verified_ci({"workflow_runs": [ci(), ci(2, attempt=2)]}, SHA))
        with self.assertRaises(sim.AdmissionError):
            sim.verified_ci({"bad": []}, SHA)

    def test_pr_not_merged_never_fetches_main_or_starts_install(self):
        queried = []
        def github(path):
            queried.append(path)
            if path == "repos/arthexis/ocpp-simulator/pulls/20":
                return {"merged": False}
            raise AssertionError("main and CI must not be queried before merge")
        with patch.object(sim, "preflight"), patch.object(sim, "github", side_effect=github), \
             patch.object(sim, "invoke", side_effect=AssertionError("no subprocess allowed")):
            self.assertTrue(sim.auto_install().startswith("SKIPPED"))
        self.assertEqual(queried, ["repos/arthexis/ocpp-simulator/pulls/20"])

    def test_pending_exact_ci_never_starts_install(self):
        def github(path):
            if path.endswith("/pulls/20"):
                return {"merged": True}
            if path.endswith("/branches/main"):
                return {"commit": {"sha": SHA}}
            return {"workflow_runs": [ci(status="in_progress", conclusion=None)]}
        with patch.object(sim, "preflight"), patch.object(sim, "github", side_effect=github), \
             patch.object(sim, "invoke", side_effect=AssertionError("CI not accepted")):
            self.assertTrue(sim.auto_install().startswith("SKIPPED"))

    def test_pointer_must_be_managed_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "current"
            self.assertEqual(sim.read_pointer(path), "")
            path.write_text("unexpected")
            with self.assertRaisesRegex(sim.AdmissionError, "non-symlink"):
                sim.read_pointer(path)
            path.unlink()
            path.symlink_to(Path(temp) / "releases" / SHA)
            self.assertTrue(sim.read_pointer(path).endswith(SHA))

    def test_installed_client_provenance_is_independently_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            verifier = source / "scripts" / "verify_main_install.py"
            verifier.parent.mkdir(parents=True)
            verifier.write_text("offline fixture")
            root = Path(temp) / "state"
            user_bin = Path(temp) / "bin"
            valid = "dep\t" + sim.MODULE + "\t" + sim.MODULE_VERSION + "\t" + sim.MODULE_SUM
            with patch.object(sim, "invoke", side_effect=["", valid]) as run:
                sim.verify_installed(source, root, user_bin, SHA, "", "")
                self.assertEqual(run.call_count, 2)
                self.assertEqual(run.call_args_list[0].args[0][1], str(verifier))
            with patch.object(sim, "invoke", side_effect=["", "dep\t" + sim.MODULE + "\tv0.19.1\twrong"]):
                with self.assertRaisesRegex(sim.AdmissionError, "pinned Go provenance"):
                    sim.verify_installed(source, root, user_bin, SHA, "", "")

    def test_workflow_uses_only_existing_gway_remote_runner(self):
        workflow = (ROOT / ".github/workflows/ocpp-simulator-deploy.yml").read_text()
        self.assertIn("schedule:", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("runs-on: [self-hosted, Linux, ARM64, gway-001]", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("python3 scripts/auto-deploy-ocpp-simulator.py", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertIn("persist-credentials: false", workflow)

    def test_fixed_repository_and_no_new_token_or_service(self):
        content = SOURCE.read_text()
        self.assertIn('REPOSITORY = "arthexis/ocpp-simulator"', content)
        self.assertIn("PR_NUMBER = 20", content)
        self.assertIn("OCPP_SIMULATOR_EXPECTED_MAIN_SHA", content)
        self.assertIn("credential.helper=!gh auth git-credential", content)
        self.assertIn("TemporaryDirectory(", content)
        self.assertIn('"clone", "--quiet"', content)
        self.assertIn("--no-checkout", content)
        self.assertIn("verify_installed(", content)
        self.assertIn('"sh", "./deploy.sh"', content)
        self.assertNotIn("subprocess.Popen", content)
        self.assertNotIn('invoke(["systemctl"', content)
        self.assertNotIn('invoke(["sudo"', content)


if __name__ == "__main__":
    unittest.main()
