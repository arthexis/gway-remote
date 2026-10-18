"""Guard manual appliance deployment and prevent unsafe manual access."""
import unittest
from pathlib import Path


class WorkflowSafetyTests(unittest.TestCase):
    def test_manual_workflow_requires_owner(self):
        source = Path(".github/workflows/appliance-deploy.yml").read_text()
        self.assertNotIn("schedule:", source)
        self.assertNotIn("GWAY_REMOTE_AUTO_ENABLED", source)
        self.assertIn("deploy-batch --all", source)
        self.assertIn("github.event_name == 'workflow_dispatch'", source)
        self.assertIn("github.actor == 'arthexis'", source)
        self.assertIn("cancel-in-progress: false", source)
        self.assertIn("self-hosted", source)

    def test_report_workflow_keeps_artifacts(self):
        source = Path(".github/workflows/appliance-report.yml").read_text()
        self.assertIn("upload-artifact@v4", source)
        self.assertIn("report-bundle", source)
        self.assertIn("retention-days: 14", source)


if __name__ == "__main__":
    unittest.main()
