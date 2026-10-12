"""Regression checks for the consolidated appliance deployment contract."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEPLOY = ROOT / ".github/workflows/deploy-backend.yml"
LEGACY = ROOT / ".github/workflows/update-gway-001.yml"


class DeploymentWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = DEPLOY.read_text()
        cls.legacy = LEGACY.read_text()

    def test_deploy_only_after_successful_main_ci(self):
        for required in (
            'workflows: ["Python checks"]',
            "workflow_run.conclusion == 'success'",
            "workflow_run.event == 'push'",
            "workflow_run.head_branch == 'main'",
            "workflow_run.head_repository.full_name == 'arthexis/gway-remote'",
            'ref: ${{ github.event.workflow_run.head_sha }}',
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.workflow)

    def test_stale_revision_skips_install(self):
        self.assertIn('if [[ "$VERIFIED_SHA" != "$CURRENT_SHA" ]]', self.workflow)
        self.assertIn('echo "skip=true" >> "$GITHUB_ENV"', self.workflow)
        self.assertGreaterEqual(self.workflow.count("if: env.skip != 'true'"), 3)

    def test_local_credential_reused(self):
        self.assertNotIn('secrets.GWAY_REMOTE_API_TOKEN', self.workflow)
        self.assertIn("token=local_api_token()", self.workflow)

    def test_transactional_deployment_module_is_invoked(self):
        self.assertIn("from gway_remote.deployment import deploy", self.workflow)
        self.assertIn("deploy(", self.workflow)
        self.assertIn('install=lambda: subprocess.run(["sh", "scripts/install-cli.sh"], check=True)', self.workflow)
        self.assertNotIn("systemctl enable", self.workflow)

    def test_one_automatic_deployer(self):
        self.assertNotIn('  push:', self.legacy)
        self.assertIn('if: ${{ false }}', self.legacy)
        self.assertIn('group: gway-001-appliance-report', self.workflow)


if __name__ == "__main__":
    unittest.main()
