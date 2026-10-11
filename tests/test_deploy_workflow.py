"""Regression checks for the consolidated appliance deployment contract."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
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

    def test_missing_secret_fails_closed(self):
        self.assertIn('secrets.GWAY_REMOTE_API_TOKEN', self.workflow)
        self.assertIn('test -n "${GWAY_REMOTE_API_TOKEN:-}"', self.workflow)
        self.assertLess(self.workflow.index('test -n "${GWAY_REMOTE_API_TOKEN:-}"'), self.workflow.index('sh scripts/install-cli.sh'))

    def test_user_bus_and_existing_service_only(self):
        self.assertIn('XDG_RUNTIME_DIR="/run/user/$(id -u)"', self.workflow)
        self.assertIn('DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"', self.workflow)
        self.assertIn('test -S "$XDG_RUNTIME_DIR/bus"', self.workflow)
        self.assertIn('systemctl --user restart gway-remote-mobile-api.service', self.workflow)
        self.assertNotIn('systemctl enable', self.workflow)

    def test_health_check_is_authenticated_and_bounded(self):
        self.assertIn('/api/v1/health', self.workflow)
        self.assertIn('"Authorization": "Bearer " + os.environ["GWAY_REMOTE_API_TOKEN"]', self.workflow)
        self.assertIn('timeout=2', self.workflow)
        self.assertIn('range(15)', self.workflow)
        self.assertIn('{"status": "ok", "api": "gway-remote/v1"}', self.workflow)

    def test_rollback_registered_before_mutation(self):
        self.assertIn('sudo -n cp -p /usr/local/bin/gway-remote "$BACKUP"', self.workflow)
        self.assertIn('trap \'restore\' ERR', self.workflow)
        self.assertLess(self.workflow.index("trap 'restore' ERR"), self.workflow.index('sh scripts/install-cli.sh'))
        self.assertIn('sudo -n install -m 755 "$BACKUP" /usr/local/bin/gway-remote', self.workflow)
        self.assertIn('if ! health; then', self.workflow)

    def test_one_automatic_deployer(self):
        self.assertNotIn('  push:', self.legacy)
        self.assertIn('if: ${{ false }}', self.legacy)
        self.assertIn('group: gway-001-appliance-report', self.workflow)


if __name__ == "__main__":
    unittest.main()
