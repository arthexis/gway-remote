"""M2b workflow inspection contracts: no network, no machine-state dependencies."""
import json
import unittest
from unittest.mock import patch

from gway_remote import github_workflows_mcp as api, mcp_agent


REPO = "arthexis/gway-remote"


class WorkflowMCPTests(unittest.TestCase):
    def test_inventory_read_only_and_reject_submit(self):
        names = {t["name"] for t in mcp_agent.list_tools()}
        self.assertTrue({"github_workflow_runs", "github_workflow_status",
                         "github_workflow_errors"} <= names)
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in mcp_agent.list_tools()))
        with self.assertRaises(ValueError):
            mcp_agent.call_tool("github_workflow_rerun", {"repository": REPO, "run_id": 1})

    def test_self_and_appliance_allowlist(self):
        self.assertIn(REPO, api._repositories())
        self.assertIn("arthexis/ocpp-csms", api._repositories())
        self.assertEqual(len(api._repositories()), len(set(api._repositories())))
        with self.assertRaisesRegex(ValueError, "repository_not_allowed"):
            api._allowed("outsider/secret")

    def test_bounded_run_listing(self):
        def fake(repo, path, params=None):
            self.assertEqual(repo, REPO)
            self.assertEqual(path, "runs")
            self.assertEqual(params["per_page"], 2)
            return {"workflow_runs": [{"id": 11, "name": "CI", "status": "completed",
                                       "conclusion": "failure", "token": "never-return"},
                                      {"id": 12, "status": "in_progress"}]}
        with patch.object(api, "_request", side_effect=fake):
            result = api.runs({"repository": REPO, "limit": 2})
        self.assertEqual(len(result["runs"]), 2)
        self.assertEqual(result["runs"][0]["conclusion"], "failure")
        self.assertNotIn("token", json.dumps(result))
        self.assertEqual(result["runs"][1]["status"], "in_progress")
        self.assertEqual(result["source"], "github_live")

    def test_status_and_failure_step(self):
        def fake(repo, path, params=None):
            self.assertEqual(repo, REPO)
            if path == "runs/14":
                return {"id": 14, "status": "completed", "conclusion": "failure"}
            if path == "runs/14/jobs":
                return {"total_count": 1, "jobs": [{"id": 50, "name": "deploy",
                       "conclusion": "failure", "steps": [{"name": "Validate",
                       "conclusion": "failure"}]}]}
            if path == "jobs/50":
                return {"id": 50, "name": "deploy", "conclusion": "failure",
                        "steps": [{"name": "Validate", "conclusion": "failure"}]}
            raise AssertionError("unexpected API route: " + path)
        with patch.object(api, "_request", side_effect=fake):
            self.assertEqual(api.status({"repository": REPO, "run_id": 14})["jobs"][0]["id"], 50)
            failure = api.errors({"repository": REPO, "run_id": 14, "job_id": 50})
        self.assertEqual(failure["failures"][0]["failed_steps"][0]["name"], "Validate")
        self.assertFalse(failure["logs_available"])

    def test_reject_unauthorized_and_invalid_input(self):
        for fn, args in [
            (api.runs, {"repository": "outsider/secret"}),
            (api.runs, {"repository": REPO, "limit": 200}),
            (api.runs, {"repository": REPO, "branch": "a?token=secret"}),
            (api.status, {"repository": REPO, "run_id": True}),
            (api.status, {"repository": REPO, "run_id": 0}),
            (api.errors, {"repository": REPO, "run_id": 14, "job_id": -1}),
        ]:
            with self.subTest(fn=fn.__name__, args=args), self.assertRaises(ValueError):
                with patch.object(api, "_request") as upstream:
                    fn(args)
                upstream.assert_not_called()

    def test_http_failure_codes_and_missing_token(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(api.WorkflowError):
                api._request(REPO, "runs")
        self.assertEqual(api.WorkflowError("github_unavailable").args[0], "github_unavailable")

    def test_truncated_jobs_fail_closed(self):
        with patch.object(api, "_request", side_effect=[
             {"id": 14}, {"total_count": 2, "jobs": [{"id": 10, "steps": []}]}]):
            with self.assertRaisesRegex(api.WorkflowError, "github_jobs_truncated"):
                api.status({"repository": REPO, "run_id": 14})


if __name__ == "__main__":
    unittest.main()
