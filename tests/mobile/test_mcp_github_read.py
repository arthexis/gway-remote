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
        with patch.object(api, "_get", side_effect=[{"total_count": 1, "check_suites": [{}]}, checks, [{"id": 4, "sha": SHA, "context": "legacy", "state": "success"}]]):
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

    def test_rules_multiple_pages(self):
        entries = [{"type": "deletion"}] * 100
        with patch.object(api, "_get", side_effect=[entries, [{"type": "required_status_checks", "parameters": {}}]]) as get:
            result = api.branch_effective_rules({"repository": REPO, "branch": "main"})
        self.assertEqual(len(result["rules"]), 101)
        self.assertEqual(get.call_count, 2)

    def test_rules_page_limit_and_malformed_rules(self):
        # Exercise the page limit with distinct records, not a repeated
        # page (which correctly fails earlier as inconsistent pagination).
        def unique_full_page(repository, path, params):
            return [{"type": "deletion", "ruleset_id": params["page"] * 100 + i}
                    for i in range(100)]
        with patch.object(api, "_get", side_effect=unique_full_page):
            with self.assertRaisesRegex(api.WorkflowError, "github_incomplete_pagination"):
                api.branch_effective_rules({"repository": REPO, "branch": "main"})
        with patch.object(api, "_get", return_value=[{"type": "required_status_checks", "parameters": []}]):
            with self.assertRaisesRegex(api.WorkflowError, "github_invalid_response"):
                api.branch_effective_rules({"repository": REPO, "branch": "main"})

    def test_cross_page_identical_rules_rejected(self):
        first = [{"type": "deletion", "ruleset_id": 101,
                  "ruleset_source": "arthexis/gway-remote"}] * 100
        with patch.object(api, "_get", side_effect=[first, [first[0]]]):
            with self.assertRaisesRegex(api.WorkflowError, "github_inconsistent_pagination"):
                api.branch_effective_rules({"repository": REPO, "branch": "main"})

    def test_same_type_different_rulesets_and_parameters_are_distinct(self):
        first = [{"type": "required_status_checks", "ruleset_id": 101,
                  "parameters": {"required_status_checks": [{"context": "CI"}]}}] * 100
        second = [{"type": "required_status_checks", "ruleset_id": 102,
                   "parameters": {"required_status_checks": [{"context": "CI"}]}},
                  {"type": "required_status_checks", "ruleset_id": 101,
                   "parameters": {"required_status_checks": [{"context": "lint"}]}}]
        with patch.object(api, "_get", side_effect=[first, second]):
            result = api.branch_effective_rules({"repository": REPO, "branch": "main"})
        self.assertEqual(len(result["rules"]), 102)

    def test_suite_first_page_count_consistency(self):
        for count, entries in ((1, []), (0, [{}]), (2, [{}, {}])):
            with self.subTest(total_count=count, entries=entries):
                with patch.object(api, "_get", return_value={
                    "total_count": count, "check_suites": entries}) as get:
                    with self.assertRaisesRegex(api.WorkflowError, "github_invalid_response"):
                        api.commit_checks({"repository": REPO, "sha": SHA})
                    self.assertEqual(get.call_count, 1)

    def test_suite_coverage_fail_closed(self):
        with patch.object(api, "_get", return_value={"total_count": 1000, "check_suites": [{}]}) as get:
            with self.assertRaisesRegex(api.WorkflowError, "github_check_suite_coverage_unknown"):
                api.commit_checks({"repository": REPO, "sha": SHA})
        self.assertEqual(get.call_count, 1)

    def test_check_semantic_validation(self):
        data = [{"total_count": 1, "check_suites": [{}]},
                {"total_count": 1, "check_runs": [{"id": 3, "head_sha": SHA, "status": "completed", "conclusion": "success"}]},
                []]
        with patch.object(api, "_get", side_effect=data):
            with self.assertRaisesRegex(api.WorkflowError, "github_invalid_response"):
                api.commit_checks({"repository": REPO, "sha": SHA})

    def test_classic_statuses_multiple_pages(self):
        first = [{"id": i, "context": "legacy", "state": "success"} for i in range(100)]
        replies = [{"total_count": 0, "check_suites": []},
                   {"total_count": 0, "check_runs": []}, first,
                   [{"id": 101, "context": "legacy", "state": "failure"}]]
        with patch.object(api, "_get", side_effect=replies):
            self.assertEqual(len(api.commit_checks({"repository": REPO, "sha": SHA})["statuses"]), 101)

    def test_redirect_is_rejected(self):
        import io
        from urllib.error import HTTPError
        self.assertIsNone(api._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://untrusted.invalid"))
        class RedirectingOpener:
            def open(self, req, timeout):
                raise HTTPError(req.full_url, 302, "Redirect", {}, io.BytesIO())
        with patch.object(api, "build_opener", return_value=RedirectingOpener()), patch.dict("os.environ", {"GWAY_MCP_GITHUB_TOKEN": "fake"}):
            with self.assertRaisesRegex(api.WorkflowError, "github_redirect_rejected"):
                api._get(REPO, "rules/branches/main")

    def test_count_drift_and_duplicate_ids(self):
        first = {"total_count": 101, "check_runs": [{"id": i} for i in range(100)]}
        with patch.object(api, "_get", side_effect=[first, {"total_count": 102, "check_runs": [{"id": 100}]}]):
            with self.assertRaisesRegex(api.WorkflowError, "github_inconsistent_pagination"):
                api._pages(REPO, "commits/" + SHA + "/check-runs", "check_runs")
        with patch.object(api, "_get", return_value={"total_count": 2, "check_runs": [{"id": 1}, {"id": 1}]}):
            with self.assertRaisesRegex(api.WorkflowError, "github_inconsistent_pagination"):
                api._pages(REPO, "commits/" + SHA + "/check-runs", "check_runs")

if __name__ == "__main__":
    unittest.main()
