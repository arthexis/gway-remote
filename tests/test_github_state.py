"""Unittest coverage for the read-only GitHub state adapter."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from gway_remote.github_state import collect, ci_for_head, main_arrival, report
from gway_remote.reconcile import TARGETS


class FakeGitHub:
    def get(self, path):
        if path.endswith("/branches/main"):
            return {"commit": {"sha": "a" * 40}}
        if "/actions/runs?" in path:
            return {"workflow_runs": [{
                "head_sha": "a" * 40, "created_at": "2026-10-09T11:00:00Z",
                "status": "completed", "conclusion": "success",
            }]}
        if "/deployments?" in path:
            return [{"id": 12, "sha": "a" * 40, "environment": "gway-001", "task": "gway-remote/reconciler/v1"}]
        if "/deployments/12/statuses?" in path:
            return [{"state": "success"}]
        raise AssertionError(path)


class TestGitHubState(unittest.TestCase):
    def test_collect_and_report(self):
        states = collect(FakeGitHub())
        self.assertEqual(len(states), len(TARGETS))
        self.assertIsNone(states[0].attempted_sha)
        result = report(FakeGitHub(), datetime(2026, 10, 9, 12, tzinfo=timezone.utc))
        self.assertEqual(result["decision"], "ready")
        self.assertEqual(len(result["attempt"]), 3)

    def test_missing_attempt_history_is_eligible(self):
        class Missing(FakeGitHub):
            def get(self, path):
                if "/deployments?" in path:
                    return []
                return super().get(path)
        result = report(Missing(), datetime(2026, 10, 9, 12, tzinfo=timezone.utc))
        self.assertEqual(result["decision"], "ready")

    def test_no_main_push_evidence_blocks(self):
        class NoRun(FakeGitHub):
            def get(self, path):
                if "/actions/runs?" in path:
                    return {"workflow_runs": []}
                return super().get(path)
        result = report(NoRun(), datetime(2026, 10, 9, 12, tzinfo=timezone.utc))
        self.assertEqual(result["decision"], "blocked")

    def test_ci_failure(self):
        class Failed(FakeGitHub):
            def get(self, path):
                value = super().get(path)
                if "/actions/runs?" in path:
                    value["workflow_runs"][0]["conclusion"] = "failure"
                return value
        self.assertEqual(ci_for_head(Failed(), TARGETS[0][1], "a" * 40), "failure")


if __name__ == "__main__":
    unittest.main()
