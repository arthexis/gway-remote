"""Regression tests for main revision discovery and blocked diagnostics."""
from datetime import datetime, timezone
import unittest

from gway_remote.github_state import main_arrival, ci_for_head
from gway_remote.attempt_policy import Candidate, plan
from gway_remote.reconcile import TARGETS


SHA = "a" * 40


class FakeGitHub:
    def __init__(self):
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        if path.endswith("/pulls"):
            return [{"number": 1, "merged_at": "2026-10-15T12:30:00Z",
                     "merge_commit_sha": SHA,
                     "base": {"ref": "main", "repo": {"full_name": "arthexis/gway-lcd-sound"}},
                     "head": {"sha": "b" * 40, "repo": {"full_name": "arthexis/gway-lcd-sound"}}}]
        if "/commits/" in path:
            return {"commit": {"committer": {"date": "2026-10-15T12:30:00Z"}}}
        return {"workflow_runs": [
            {"event": "pull_request", "head_sha": "b" * 40, "pull_requests": [], "status": "completed", "conclusion": "success"}
        ]}


class RevisionDiscoveryTests(unittest.TestCase):
    def test_timestamp_does_not_depend_on_recent_workflow_runs(self):
        client = FakeGitHub()
        value = main_arrival(client, "arthexis/gway-lcd-sound", SHA)
        self.assertEqual(value, datetime(2026, 10, 15, 12, 30, tzinfo=timezone.utc))
        self.assertEqual(client.paths, [f"repos/arthexis/gway-lcd-sound/commits/{SHA}"])

    def test_ci_queries_exact_sha_not_latest_fifty_runs(self):
        client = FakeGitHub()
        self.assertEqual(ci_for_head(client, "arthexis/gway-lcd-sound", SHA), "success")
        self.assertIn(f"commits/{SHA}/pulls", client.paths[0])
        self.assertIn(f"head_sha={\"b\" * 40}", client.paths[1])

    def test_missing_commit_date_identifies_component(self):
        now = datetime(2026, 10, 16, tzinfo=timezone.utc)
        candidates = tuple(Candidate(name, SHA, None if name == "gway-lcd-sound" else now, "success")
                           for name, _ in TARGETS)
        decision = plan(candidates, now)
        self.assertEqual(decision.state, "blocked")
        self.assertIn("gway-lcd-sound", decision.reason)


if __name__ == "__main__":
    unittest.main()
