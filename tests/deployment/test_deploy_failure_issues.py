"""Regression tests for deduplicated appliance deployment incidents."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.deploy_failure_issues import issue_body, upsert, report_failures


class FailureIssueTests(unittest.TestCase):
    @patch("gway_remote.deploy_failure_issues.gh_json")
    def test_existing_open_component_issue_is_updated(self, api):
        api.side_effect = [
            [{"number": 11, "body": "<!-- gway-remote:deployment-failure:ocpp-reports -->"}],
            {"number": 11, "html_url": "https://github.com/arthexis/gway-remote/issues/11"},
        ]
        upsert("arthexis/gway-remote", "ocpp-reports", "new report")
        self.assertIn("issues/11", api.call_args.args[0])
        self.assertIn("PATCH", api.call_args.args)

    @patch("gway_remote.deploy_failure_issues.gh_json")
    def test_closed_or_unrelated_issue_is_not_overwritten(self, api):
        api.side_effect = [
            [{"number": 11, "body": "unrelated"}],
            {"number": 12, "html_url": "https://github.com/arthexis/gway-remote/issues/12"},
        ]
        upsert("arthexis/gway-remote", "ocpp-reports", "new report")
        self.assertEqual(api.call_args.args[0], "repos/arthexis/gway-remote/issues")
        self.assertIn("POST", api.call_args.args)

    def test_issue_contains_run_and_truncated_diagnostics(self):
        body = issue_body("gway-lcd-sound", "failure", "https://github.com/run/123",
                          "sanitized summary", "x" * 10000)
        self.assertIn("run/123", body)
        self.assertIn("deployment-failure:gway-lcd-sound", body)
        self.assertLess(len(body), 7000)

    @patch("gway_remote.deploy_failure_issues.upsert")
    def test_only_failed_selected_component_published(self, publish):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "summary.md").write_text("Safe appliance summary")
            (d / "summary.json").write_text('{"components": []}')
            jobs = {"ocpp_reports": {"result": "failure"},
                    "gway_lcd_sound": {"result": "failure"}}
            report_failures("arthexis/gway-remote", "https://github.com/run/2",
                            "ocpp-reports", jobs, d)
            self.assertEqual(publish.call_count, 1)
            self.assertEqual(publish.call_args.args[1], "ocpp-reports")


if __name__ == "__main__":
    unittest.main()
