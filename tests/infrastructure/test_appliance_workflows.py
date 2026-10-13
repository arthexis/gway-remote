"""Keep reporting read-only and all appliance deployment in its own workflow."""
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


class ApplianceWorkflowTests(unittest.TestCase):
    def test_report_has_no_deployment_path(self):
        report = (WORKFLOWS / "appliance-report.yml").read_text()
        self.assertIn("workflow_dispatch:", report)
        self.assertIn("report-bundle", report)
        self.assertNotIn("schedule:", report)
        self.assertNotIn("deploy-batch", report)
        self.assertNotIn("GH_TOKEN", report)
        self.assertNotIn("GWAY_REMOTE_AUTO_ENABLED", report)

    def test_deployment_manual_override_and_scheduled_gating(self):
        deploy = (WORKFLOWS / "appliance-deploy.yml").read_text()
        self.assertIn("workflow_dispatch:", deploy)
        self.assertIn("schedule:", deploy)
        self.assertIn("GWAY_REMOTE_AUTO_ENABLED", deploy)
        self.assertIn("github.actor == 'arthexis'", deploy)
        self.assertIn("deploy-batch --now", deploy)
        self.assertIn("deploy-batch --now --retry-failed", deploy)
        self.assertIn("RETRY_FAILED", deploy)
        self.assertIn("deploy-batch\n", deploy)
        self.assertIn("report-bundle", deploy)
        self.assertIn("exit_code", deploy)

    def test_workflows_share_appliance_concurrency_lock(self):
        report = (WORKFLOWS / "appliance-report.yml").read_text()
        deploy = (WORKFLOWS / "appliance-deploy.yml").read_text()
        self.assertIn("group: gway-001-appliance", report)
        self.assertIn("group: gway-001-appliance", deploy)


if __name__ == "__main__":
    unittest.main()
