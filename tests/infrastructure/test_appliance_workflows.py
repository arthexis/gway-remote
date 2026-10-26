"""Keep reporting read-only and all appliance deployment in its own workflow."""
import unittest
import re
from gway_remote.reconcile import TARGETS
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
        for name, _ in TARGETS:
            with self.subTest(repository=name):
                self.assertIn(f"deploy-batch --all --target {name}", deploy)
                self.assertIn(f"name: Deploy {name}", deploy)
        self.assertIn("report-bundle", deploy)
        self.assertEqual(len(TARGETS), deploy.count("python3 -m gway_remote deploy-batch --all --target"))

    def test_two_independent_serialized_tracks(self):
        deploy = (WORKFLOWS / "appliance-deploy.yml").read_text()
        # Extract top-level job blocks, independent of incidental formatting.
        blocks = re.split(r"(?m)^  ([a-z][a-z0-9_]*):\s*\n", deploy.split("\njobs:\n", 1)[1])
        jobs = dict(zip(blocks[1::2], blocks[2::2]))

        tracks = (
            ("ocpp_csms", "ocpp_reports", "ocpp_simulator"),
            ("gway_lcd_sound", "gway_agent_ops", "gway_ap_kiosk",
             "gway_rfid", "gway_bastion"),
        )
        self.assertEqual(set(jobs), {"admission", "report"} | set().union(*map(set, tracks)))
        self.assertIn("require_local_deployment", jobs["admission"])
        for track in tracks:
            for index, job in enumerate(track):
                with self.subTest(job=job):
                    dependencies = re.findall(r"(?m)^    needs:\s*(.+)$", jobs[job])
                    self.assertEqual(dependencies, ["[admission, " + track[index - 1] + "]"] if index else ["admission"])
                    if index:
                        self.assertIn("always()", jobs[job])
                    self.assertIn("deploy-batch --all --target", jobs[job])

        self.assertIn("always()", jobs["report"])
        self.assertIn("needs: [admission, " + ", ".join(name.replace("-", "_") for name, _ in TARGETS) + "]",
                      jobs["report"])
        self.assertIn("JOB_RESULTS: ${{ toJSON(needs) }}", jobs["report"])
        self.assertIn("Summarize independent deployment outcomes", jobs["report"])
        self.assertIn('outcome = "not selected"', jobs["report"])
        self.assertIn('outcome = results[job]["result"]', jobs["report"])
        self.assertNotIn("exit 0", deploy)

    def test_workflows_share_appliance_concurrency_lock(self):
        report = (WORKFLOWS / "appliance-report.yml").read_text()
        deploy = (WORKFLOWS / "appliance-deploy.yml").read_text()
        self.assertIn("group: gway-001-appliance", report)
        self.assertIn("group: gway-001-appliance", deploy)


if __name__ == "__main__":
    unittest.main()
