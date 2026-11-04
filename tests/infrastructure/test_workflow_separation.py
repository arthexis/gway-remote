"""Guard the PR-only test / main-only deploy workflow separation."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github/workflows/ci.yml"
DEPLOY = ROOT / ".github/workflows/deploy-backend.yml"


class WorkflowSeparationTests(unittest.TestCase):
    def test_ci_only_runs_on_pull_requests(self):
        text = CI.read_text()
        self.assertIn("on:\n  pull_request:\n", text)
        self.assertNotIn("  push:\n    branches: [main]", text)
        self.assertIn("name: CI", text)
        self.assertIn("needs: [unit, webauthn-python310, validation, ansible-core-2-12, ssh-config]", text)
        self.assertIn("webauthn-python310:", text)
        self.assertIn('result["result"] != "success"', text)

    def test_deployment_runs_on_main_push_not_ci_completion(self):
        text = DEPLOY.read_text()
        self.assertIn("on:\n  push:\n    branches: [main]", text)
        self.assertNotIn("workflow_run:", text)
        self.assertIn("github.sha", text)
        self.assertIn("CURRENT_SHA", text)
        self.assertIn("Transactional install, restart and authenticated health", text)

    def test_deployment_does_not_repeat_unit_tests(self):
        text = DEPLOY.read_text()
        self.assertNotIn("unittest discover", text)
        self.assertNotIn("pytest", text)
        self.assertNotIn("Validate backend before installation", text)
        self.assertIn("command -v ansible-playbook", text)


if __name__ == "__main__":
    unittest.main()
