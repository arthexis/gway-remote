"""Regression tests for deduplicated appliance deployment incidents."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.deploy_failure_issues import (
    REPOSITORIES, issue_body, upsert, report_failures, require_job_results,
)


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

    def _report(self, selected, results):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "summary.md").write_text("Safe appliance summary")
            (d / "summary.json").write_text('{"components": []}')
            report_failures("arthexis/gway-remote", "https://github.com/run/2",
                            selected, results, d)

    @staticmethod
    def _jobs(**results):
        # GitHub toJSON(needs) contains every job, including skipped entries.
        jobs = {job: {"result": "skipped"} for job in REPOSITORIES}
        jobs["admission"] = {"result": "success"}
        for job, result in results.items():
            jobs[job] = {"result": result}
        return jobs

    @patch("gway_remote.deploy_failure_issues.upsert")
    def test_only_failed_selected_component_published(self, publish):
        self._report("gway-lcd-sound",
                     self._jobs(gway_lcd_sound="failure", ocpp_csms="failure"))
        publish.assert_called_once()
        self.assertEqual(publish.call_args.args[1], "gway-lcd-sound")

    @patch("gway_remote.deploy_failure_issues.upsert")
    def test_all_reports_each_failed_real_job_including_bastion(self, publish):
        self._report("all", self._jobs(
            ocpp_csms="failure", gway_lcd_sound="cancelled",
            gway_bastion="timed_out"))
        self.assertEqual([c.args[1] for c in publish.call_args_list],
                         ["ocpp-csms", "gway-lcd-sound", "gway-bastion"])
        self.assertNotIn("ocpp-simulator", REPOSITORIES.values())
        # Reports must enter this map when PR #564 admits it to the dispatcher.
        from gway_remote.deploy_dispatch import TARGETS
        self.assertEqual(set(REPOSITORIES.values()), set(TARGETS) - {"all"})

    @patch("gway_remote.deploy_failure_issues.upsert")
    def test_missing_or_extra_job_fails_before_any_write(self, publish):
        fixtures = [
            {k: v for k, v in self._jobs().items() if k != "gway_rfid"},
            {**self._jobs(), "ocpp_simulator": {"result": "failure"}},
            {**self._jobs(), "ocpp_reports": {"result": "failure"}}
            if "ocpp_reports" not in REPOSITORIES else
            {**self._jobs(), "phantom_job": {"result": "failure"}},
        ]
        for jobs in fixtures:
            with self.subTest(jobs=sorted(jobs)):
                with self.assertRaisesRegex(ValueError, "job results mismatch"):
                    self._report("all", jobs)
        publish.assert_not_called()

    @patch("gway_remote.deploy_failure_issues.upsert")
    def test_invalid_results_or_admission_fail_closed(self, publish):
        for selected, jobs in (
            ("invalid", self._jobs()),
            ("all", {**self._jobs(), "ocpp_csms": {}}),
            ("all", {**self._jobs(), "admission": {"result": "failure"}}),
            ("all", {**self._jobs(), "gway_rfid": {"result": "unknown"}}),
        ):
            with self.subTest(selected=selected, jobs=jobs):
                with self.assertRaises(ValueError):
                    self._report(selected, jobs)
        publish.assert_not_called()

    def test_job_result_validation_does_not_execute_gh(self):
        with patch("gway_remote.deploy_failure_issues.gh_json") as api:
            require_job_results("all", self._jobs())
            api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
