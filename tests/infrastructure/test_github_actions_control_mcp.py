"""Hermetic GitHub Actions MCP: pagination, scope, errors and non-deployment."""
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from gway_remote import github_actions_control as actions
from gway_remote import github_workflows_mcp as legacy
from gway_remote import mcp_agent


REPO = "arthexis/gway-remote"


def run(run_id, status="completed", conclusion="success"):
    return {"id": run_id, "name": "CI", "workflow_id": 5, "head_branch": "main",
            "head_sha": "a" * 40, "event": "pull_request", "status": status,
            "conclusion": conclusion, "created_at": "2026-11-20T00:00:00Z",
            "updated_at": "2026-11-20T00:00:01Z", "html_url": "https://github.com/example"}


class GitHubActionsControlTests(unittest.TestCase):
    def test_workflows_page_two_and_more(self):
        payload = {"total_count": 41, "workflows": [
            {"id": 123, "name": "CI", "path": ".github/workflows/ci.yml",
             "state": "active", "html_url": "https://github.com/example"}]}
        with patch.object(actions, "_request", return_value=payload) as request:
            result = actions.workflow_list({"repository": REPO, "page": 2, "limit": 20})
        request.assert_called_once_with(REPO, "workflows", {"per_page": 20, "page": 2})
        self.assertEqual(result["workflows"][0]["id"], 123)
        self.assertTrue(result["pagination"]["has_more"])

    def test_workflows_reject_bad_count_and_repo(self):
        with patch.object(actions, "_request", return_value={"workflows": []}):
            with self.assertRaisesRegex(legacy.WorkflowError, "github_invalid_response"):
                actions.workflow_list({"repository": REPO})
        with self.assertRaisesRegex(ValueError, "repository_not_allowed"):
            actions.workflow_list({"repository": "someone/other"})

    def test_paged_runs_filter_and_per_repo_count(self):
        with patch.object(legacy, "_request", return_value={
                "total_count": 37, "workflow_runs": [run(9)]}) as request:
            result = legacy.runs({"repository": REPO, "workflow_id": 5,
                                  "page": 2, "limit": 20, "status": "completed"})
        request.assert_called_once_with(REPO, "workflows/5/runs", {
            "per_page": 20, "page": 2, "status": "completed"})
        self.assertEqual(result["runs"][0]["id"], 9)
        self.assertFalse(result["pagination"]["has_more"])

    def test_legacy_runs_contract_unchanged(self):
        with patch.object(legacy, "_request", return_value={"workflow_runs": [run(7)]}):
            result = legacy.runs({"repository": REPO})
        self.assertEqual(set(result), {"source", "runs"})
        self.assertEqual(result["runs"][0]["id"], 7)

    def test_paged_runs_fail_closed_on_truncated_payload(self):
        with patch.object(legacy, "_request", return_value={
                "workflow_runs": [run(1)], "total_count": "unknown"}):
            with self.assertRaisesRegex(legacy.WorkflowError, "github_invalid_response"):
                legacy.runs({"repository": REPO, "page": 2})

    def test_health_identifies_failure_without_false_global_certification(self):
        payload = {"total_count": 31, "workflow_runs": [
            run(1, "completed", "failure"), run(2, "in_progress", None),
            run(3, "completed", "success")]}
        with patch.object(legacy, "_request", return_value=payload):
            result = actions.workflow_health({"repository": REPO, "limit": 10})
        self.assertEqual(result["state"], "failure_observed")
        self.assertEqual(result["counts"], {"success": 1, "failure": 1,
                                            "pending": 1, "other": 0})
        self.assertTrue(result["older_runs_unchecked"])
        self.assertEqual(result["scope"], "recent_runs_only")

    def test_health_empty_is_unknown(self):
        with patch.object(legacy, "_request", return_value={
                "total_count": 0, "workflow_runs": []}):
            result = actions.workflow_health({"repository": REPO})
        self.assertEqual(result["state"], "unknown")

    def test_declarations_align_with_dispatch_indices(self):
        self.assertEqual([tool["name"] for tool in mcp_agent.TOOLS],
                         list(mcp_agent._HANDLERS))

    def test_read_tool_scope_and_write_denied_before_network(self):
        names = {t["name"]: t for t in mcp_agent.TOOLS}
        self.assertEqual(names["github_workflow_list"]["annotations"]["readOnlyHint"], True)
        self.assertEqual(names["github_workflow_health"]["annotations"]["readOnlyHint"], True)
        for name, data in (("github_workflow_dispatch",
                            {"repository": REPO, "workflow_id": 1, "ref": "main"}),
                           ("github_workflow_cancel",
                            {"repository": REPO, "run_id": 1})):
            with self.subTest(name=name), patch.object(actions, "_post") as write:
                with self.assertRaisesRegex(ValueError, "mcp_execute_scope_required"):
                    mcp_agent.call_tool(name, data, authorized_scope="read")
                write.assert_not_called()

    def test_dispatch_and_cancel_use_existing_execute_scope(self):
        with patch.object(actions, "_post") as post:
            result = mcp_agent.call_tool(
                "github_workflow_dispatch",
                {"repository": REPO, "workflow_id": 11, "ref": "main",
                 "inputs": {"node": "gway-001"}}, authorized_scope="execute")
            post.assert_called_once_with(REPO, "workflows/11/dispatches",
                                         {"ref": "main", "inputs": {"node": "gway-001"}}, 204)
            self.assertTrue(result["accepted"])
            self.assertFalse(result["execution_verified"])
        with patch.object(actions, "_post") as post:
            result = mcp_agent.call_tool(
                "github_workflow_cancel", {"repository": REPO, "run_id": 22},
                authorized_scope="execute")
            post.assert_called_once_with(REPO, "runs/22/cancel", {}, 202)
            self.assertFalse(result["cancelled_verified"])

    def test_invalid_reference_and_inputs_fail_without_post(self):
        with patch.object(actions, "_post") as post:
            for ref in ("../main", "/main", "main//foo", "main?abc"):
                with self.subTest(ref=ref), self.assertRaises(ValueError):
                    actions.workflow_dispatch({"repository": REPO, "workflow_id": 1,
                                               "ref": ref})
            with self.assertRaisesRegex(ValueError, "unsupported_ref"):
                actions.workflow_dispatch({"repository": REPO, "workflow_id": 1,
                                           "ref": "feature/unreviewed"})
            for inputs in ({"bad key": "value"}, {"okay": ["not string"]},
                           {"key": "x" * 201}):
                with self.assertRaisesRegex(ValueError, "invalid_inputs"):
                    actions.workflow_dispatch({"repository": REPO,
                                               "workflow_id": 1, "ref": "main",
                                               "inputs": inputs})
            post.assert_not_called()

    def test_no_arbitrary_repo_or_node_deploy(self):
        with patch.object(actions, "_post") as post:
            with self.assertRaisesRegex(ValueError, "repository_not_allowed"):
                actions.workflow_cancel({"repository": "outside/repo", "run_id": 42})
            post.assert_not_called()
        self.assertNotIn("node_deploy", actions.__dict__)
        self.assertNotIn("node_exec", actions.__dict__)

    def test_post_exact_204_no_redirect_and_existing_token(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.getcode.return_value = 204
        opener = Mock()
        opener.open.return_value = response
        with patch.dict(actions.os.environ, {"GWAY_MCP_GITHUB_TOKEN": "fake-token"}), \
             patch.object(actions, "build_opener", return_value=opener) as build:
            actions._post(REPO, "workflows/123/dispatches",
                          {"ref": "main", "inputs": {}}, 204)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url,
                         "https://api.github.com/repos/arthexis/gway-remote/actions/workflows/123/dispatches")
        self.assertEqual(json.loads(request.data), {"ref": "main", "inputs": {}})
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-token")
        self.assertEqual(build.call_args.args[0].__name__, "_NoRedirect")

    def test_post_http_error_and_unknown_network_outcome(self):
        with patch.dict(actions.os.environ, {"GWAY_MCP_GITHUB_TOKEN": "fake-token"}), \
             patch.object(actions, "build_opener") as build:
            build.return_value.open.side_effect = HTTPError(
                "https://api.github.com", 403, "denied", {}, io.BytesIO(b"secret"))
            with self.assertRaisesRegex(legacy.WorkflowError, "github_http_403"):
                actions.workflow_cancel({"repository": REPO, "run_id": 5})
            build.return_value.open.side_effect = URLError("network down")
            with self.assertRaisesRegex(legacy.WorkflowError, "github_result_unknown"):
                actions.workflow_cancel({"repository": REPO, "run_id": 5})

    def test_missing_runtime_token_fails_closed(self):
        with patch.dict(actions.os.environ, {}, clear=True):
            with self.assertRaisesRegex(legacy.WorkflowError, "github_not_configured"):
                actions.workflow_cancel({"repository": REPO, "run_id": 5})


if __name__ == "__main__":
    unittest.main()
