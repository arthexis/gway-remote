"""Tests for the operator-facing GitHub deployment dispatcher."""
import subprocess
import unittest
from unittest.mock import patch

from gway_remote.deploy_dispatch import TARGETS, dispatch, follow_run


class DeployDispatchTests(unittest.TestCase):
    @patch("gway_remote.deploy_dispatch.subprocess.run")
    def test_all_targets_dispatch_with_fixed_workflow(self, run):
        for target in TARGETS:
            with self.subTest(target=target):
                message = dispatch(target)
                self.assertIn(target, message)
                self.assertIn("pending", message)
                args, kwargs = run.call_args
                self.assertEqual(args[0], [
                    "gh", "api", "--method", "POST",
                    "repos/arthexis/gway-remote/actions/workflows/appliance-deploy.yml/dispatches",
                    "-f", "ref=main", "-f", f"inputs[repository]={target}",
                    "-F", "return_run_details=true",
                ])
                self.assertTrue(kwargs["check"])

    @patch("gway_remote.deploy_dispatch.subprocess.run")
    def test_exact_run_id_is_displayed(self, run):
        run.return_value.stdout = '{"workflow_run_id":39106912358,"html_url":"https://github.com/arthexis/gway-remote/actions/runs/39106912358"}'
        message = dispatch("ocpp-reports")
        self.assertIn("workflow run 39106912358", message)
        self.assertIn("/actions/runs/39106912358", message)

    @patch("gway_remote.deploy_dispatch.subprocess.run")
    def test_no_run_id_does_not_guess(self, run):
        run.return_value.stdout = ""
        message = dispatch("ocpp-reports")
        self.assertIn("run ID unavailable", message)
        self.assertNotIn("/actions/runs/", message)

    @patch("gway_remote.deploy_dispatch.subprocess.run")
    def test_follow_watches_exact_run_and_propagates_failure(self, run):
        message = ("Requested ocpp-csms deployment: workflow run 39106912358\\n"
                   "https://github.com/arthexis/gway-remote/actions/runs/39106912358")
        follow_run(message)
        self.assertEqual(run.call_args.args[0], [
            "gh", "run", "watch", "39106912358", "--repo",
            "arthexis/gway-remote", "--exit-status", "--interval", "3"])
        self.assertTrue(run.call_args.kwargs["check"])
        run.side_effect = subprocess.CalledProcessError(1, ["gh"])
        with self.assertRaisesRegex(RuntimeError, "39106912358"):
            follow_run(message)

    @patch("gway_remote.deploy_dispatch.subprocess.run")
    def test_follow_never_guesses_missing_run_id(self, run):
        with self.assertRaisesRegex(RuntimeError, "run ID"):
            follow_run("Requested deployment; run ID unavailable")
        run.assert_not_called()

    def test_target_is_required(self):
        with self.assertRaises(TypeError):
            dispatch()

    @patch("gway_remote.deploy_dispatch.subprocess.run")
    def test_invalid_target_cannot_dispatch(self, run):
        with self.assertRaises(ValueError):
            dispatch("../../another-workflow")
        run.assert_not_called()

    @patch("gway_remote.deploy_dispatch.subprocess.run", side_effect=FileNotFoundError())
    def test_missing_gh_is_actionable(self, run):
        with self.assertRaisesRegex(RuntimeError, "gh"):
            dispatch("ocpp-csms")

    @patch("gway_remote.deploy_dispatch.subprocess.run")
    @patch.dict("os.environ", {"GITHUB_TOKEN": "token-for-test"}, clear=True)
    def test_github_token_is_forwarded_to_gh(self, run):
        dispatch("ocpp-csms")
        self.assertEqual(run.call_args.kwargs["env"]["GH_TOKEN"], "token-for-test")

    @patch("gway_remote.deploy_dispatch.subprocess.run")
    def test_gh_failure_is_not_reported_as_success(self, run):
        run.side_effect = subprocess.CalledProcessError(1, ["gh"], stderr="permission denied")
        with self.assertRaisesRegex(RuntimeError, "permission denied"):
            dispatch("ocpp-csms")


if __name__ == "__main__":
    unittest.main()
