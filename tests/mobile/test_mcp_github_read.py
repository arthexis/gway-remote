"""Hermetic GitHub MCP read-only contracts; no network access."""
import os
import unittest
from unittest.mock import patch
from gway_remote import github_read_mcp as api, mcp_agent

REPO = "arthexis/gway-remote"
SHA = "a" * 40

class GitHubReadTests(unittest.TestCase):
    def test_catalog_and_scope(self):
        names = {t["name"]: t for t in mcp_agent.list_tools()}
        for name in ("github_branch_effective_rules", "github_commit_checks"):
            self.assertTrue(names[name]["annotations"]["readOnlyHint"])
        with patch.object(api, "_get", return_value=[]):
            self.assertEqual(mcp_agent.call_tool("github_branch_effective_rules",
                {"repository": REPO, "branch": "main"}, authorized_scope="read")["rules"], [])

    def test_rules_normalized(self):
        raw = [{"type": "required_status_checks", "ruleset_id": 1,
                "parameters": {"required_status_checks": [{"context": "CI", "integration_id": 15368}]}}]
        with patch.object(api, "_get", return_value=raw) as get:
            value = api.branch_effective_rules({"repository": REPO, "branch": "main"})
        self.assertTrue(value["complete"])
        self.assertEqual(value["rules"][0]["ruleset_id"], 1)
        self.assertEqual(get.call_args.args[1], "rules/branches/main")

    def test_checks_and_classic(self):
        checks = {"total_count": 1, "check_runs": [
            {"id": 3, "head_sha": SHA, "name": "CI", "status": "completed",
             "conclusion": "success", "app": {"id": 15368}}]}
        with patch.object(api, "_get", side_effect=[checks, [{"id": 4, "sha": SHA, "context": "legacy", "state": "success"}]]):
            value = api.commit_checks({"repository": REPO, "sha": SHA})
        self.assertEqual(value["check_runs"][0]["app_id"], 15368)
        self.assertEqual(value["statuses"][0]["context"], "legacy")

    def test_fail_closed_and_no_network(self):
        for fn, arguments in (
            (api.branch_effective_rules, {"repository": "outside/repo", "branch": "main"}),
            (api.branch_effective_rules, {"repository": REPO, "branch": "../bad"}),
            (api.commit_checks, {"repository": REPO, "sha": "short"}),
            (api.commit_checks, {"repository": REPO, "sha": True}),
        ):
            with self.subTest(arguments=arguments), patch.object(api, "_get") as get:
                with self.assertRaises(ValueError):
                    fn(arguments)
                get.assert_not_called()

    def test_pagination_rejects_partial(self):
        with patch.object(api, "_get", return_value={"total_count": 2, "check_runs": [{"id": 1}]}):
            with self.assertRaisesRegex(api.WorkflowError, "github_incomplete_pagination"):
                api._pages(REPO, "commits/" + SHA + "/check-runs", "check_runs")

    def test_missing_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(api.WorkflowError, "github_not_configured"):
                api._get(REPO, "rules/branches/main")

if __name__ == "__main__":
    unittest.main()
