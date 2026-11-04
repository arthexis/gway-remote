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

    def test_deploy_runs_on_main_and_never_repeats_pr_suite(self):
        for required in (
            "  push:",
            "    branches: [main]",
            "github.ref == 'refs/heads/main'",
            'ref: ${{ github.sha }}',
            "Check deployment prerequisites",
            "Transactional install, restart and authenticated health",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.workflow)
        for prohibited in ("workflow_run:", "unittest discover", "pytest"):
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, self.workflow)

    def test_stale_revision_skips_install(self):
        self.assertIn('if [[ "$TARGET_SHA" != "$CURRENT_SHA" ]]', self.workflow)
        self.assertIn('echo "skip=true" >> "$GITHUB_ENV"', self.workflow)
        self.assertGreaterEqual(self.workflow.count("if: env.skip != 'true'"), 3)

    def test_local_credential_reused(self):
        self.assertNotIn('secrets.GWAY_REMOTE_API_TOKEN', self.workflow)
        self.assertIn("token=local_api_token()", self.workflow)

    def test_transactional_deployment_module_is_invoked(self):
        self.assertIn("from gway_remote.deployment import deploy", self.workflow)
        self.assertIn("deploy(", self.workflow)
        # The installer callback now returns whether a deployment changed the
        # installed release. A verified no-op must still pass the health probe
        # while skipping the Mobile API restart.
        self.assertIn("def install():", self.workflow)
        self.assertIn('env["GWAY_REMOTE_DEPLOY_NOOP_FILE"] = str(marker)', self.workflow)
        self.assertIn('subprocess.run(["sh", "deploy.sh"], check=True, env=env)', self.workflow)
        self.assertIn('return not (marker.is_file() and marker.read_text().strip() == "skipped")',
                      self.workflow)
        self.assertIn("deploy(token=local_api_token(), install=install)", self.workflow)
        self.assertNotIn("systemctl enable", self.workflow)

    def test_one_automatic_deployer(self):
        self.assertNotIn('  push:', self.legacy)
        self.assertIn('if: ${{ false }}', self.legacy)
        self.assertIn('group: gway-001-appliance-report', self.workflow)


if __name__ == "__main__":
    unittest.main()
