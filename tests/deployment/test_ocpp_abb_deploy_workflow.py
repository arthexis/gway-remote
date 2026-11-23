"""Hermetic guardrails for the fixed OCPP ABB deployment path."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/deploy-ocpp-abb-1.sh"
WORKFLOW = ROOT / ".github/workflows/ocpp-abb-deploy.yml"


class OcppAbbDeployWorkflowTests(unittest.TestCase):
    def test_bash_syntax(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)

    def test_fixed_ssh_target_and_remote_identity(self):
        script = SCRIPT.read_text()
        self.assertIn("StrictHostKeyChecking=yes", script)
        self.assertIn("ocpp-abb-1", script)
        self.assertIn('[[ "$(hostname -s)" == "gway-001" ]]', script)
        self.assertIn('[[ "$(hostname -s)" == "ocpp-abb-1" ]]', script)
        self.assertIn('[[ "$(id -un)" == "ubuntu" ]]', script)
        self.assertIn("git merge --ff-only FETCH_HEAD", script)
        self.assertIn("flock -n 9", script)
        self.assertIn("git status --porcelain", script)
        self.assertIn("./deploy.sh --watchtower", script)
        self.assertIn("  ./deploy.sh\n", script)
        self.assertNotIn("StrictHostKeyChecking=no", script)

    def test_dispatch_cannot_choose_host_or_arbitrary_repository(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("github.actor == 'arthexis'", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("gway-001", workflow)
        self.assertIn("ocpp-csms", workflow)
        self.assertIn("ocpp-reports", workflow)
        self.assertIn("preview", workflow)
        self.assertIn("deploy", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertNotIn("secrets.", workflow)


if __name__ == "__main__":
    unittest.main()
