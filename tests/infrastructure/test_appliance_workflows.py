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

    def test_manual_deployment_only(self):
        deploy = (WORKFLOWS / "appliance-deploy.yml").read_text()
        self.assertIn("workflow_dispatch:", deploy)
        self.assertNotIn("schedule:", deploy)
        self.assertIn("github.actor == 'arthexis'", deploy)
        for name in ("ocpp-csms", "ocpp-simulator", "gway-lcd-sound", "gway-agent-ops"):
            with self.subTest(repository=name):
                self.assertIn(f"deploy-batch --all --target {name}", deploy)
                self.assertIn(f"name: Deploy {name}", deploy)
        self.assertIn("report-bundle", deploy)
        self.assertEqual(4, deploy.count("python3 -m gway_remote deploy-batch --all --target"))

    def test_serialized_jobs_continue_after_individual_failure(self):
        deploy = (WORKFLOWS / "appliance-deploy.yml").read_text()
        for dependency in ("ocpp_csms", "ocpp_simulator", "gway_lcd_sound"):
            self.assertIn(f"needs: {dependency}", deploy)
        self.assertIn("needs: [ocpp_csms, ocpp_simulator, gway_lcd_sound, gway_agent_ops]", deploy)
        self.assertEqual(4, deploy.count("always() && github.event_name"))
        self.assertNotIn("exit 0", deploy)

    def test_workflows_share_appliance_concurrency_lock(self):
        report = (WORKFLOWS / "appliance-report.yml").read_text()
        deploy = (WORKFLOWS / "appliance-deploy.yml").read_text()
        self.assertIn("group: gway-001-appliance", report)
        self.assertIn("group: gway-001-appliance", deploy)


if __name__ == "__main__":
    unittest.main()
