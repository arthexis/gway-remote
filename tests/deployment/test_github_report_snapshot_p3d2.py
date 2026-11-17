"""#565 P3-D2: one checked catalog snapshot flows through collector and pure policy."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from gway_remote import github_state
from gway_remote.catalog_shadow import load_catalog
from gway_remote.reconcile import TARGETS


NOW = datetime(2026, 11, 17, 3, 20, tzinfo=timezone.utc)
SHA = "a" * 40
OLD = "b" * 40
ARRIVED = NOW - timedelta(minutes=20)


class GitHubReportCatalogP3D2Tests(unittest.TestCase):
    def setUp(self):
        self.client = object()
        self.sources = [repo for _, repo in TARGETS]

    def test_report_uses_one_checked_snapshot_and_unchanged_output(self):
        calls = []
        original = load_catalog
        with patch.object(github_state, "load_catalog", side_effect=lambda: (
                calls.append(("catalog",)) or original())) as loader, \
             patch.object(github_state, "main_head", side_effect=lambda c, r: (
                 calls.append(("head", r)) or SHA)), \
             patch.object(github_state, "main_arrival", side_effect=lambda c, r, sha: (
                 calls.append(("arrival", r, sha)) or ARRIVED)), \
             patch.object(github_state, "ci_for_head", side_effect=lambda c, r, sha: (
                 calls.append(("ci", r, sha)) or "success")):
            result = github_state.report(self.client, now=NOW,
                                         attempts={TARGETS[0][0]: OLD})
        loader.assert_called_once_with()
        self.assertEqual(calls, [("catalog",)] + [
            call for repo in self.sources for call in (
                ("head", repo), ("arrival", repo, SHA), ("ci", repo, SHA))])
        self.assertEqual(result["decision"], "ready")
        self.assertEqual([r["name"] for r in result["targets"]],
                         [name for name, _ in TARGETS])
        self.assertEqual(result["targets"][0]["last_attempted"], OLD)
        self.assertEqual([r["name"] for r in result["attempt"]],
                         [name for name, _ in TARGETS])
        self.assertTrue(all(r["sha"] == SHA for r in result["attempt"]))
        self.assertEqual(set(result), {"decision", "reason", "targets", "attempt"})

    def test_plan_receives_exact_same_snapshot_used_for_collection(self):
        from gway_remote import attempt_policy
        expected = tuple((t.id, t.repository) for t in load_catalog().targets)
        real_plan = attempt_policy.plan
        seen = []
        def record_plan(states, now, **kwargs):
            seen.append((tuple(s.name for s in states), kwargs["catalog_targets"]))
            return real_plan(states, now, **kwargs)
        with patch.object(github_state, "main_head", return_value=SHA), \
             patch.object(github_state, "main_arrival", return_value=ARRIVED), \
             patch.object(github_state, "ci_for_head", return_value="success"), \
             patch.object(github_state, "plan", side_effect=record_plan):
            github_state.report(self.client, now=NOW)
        self.assertEqual(seen, [(tuple(name for name, _ in TARGETS), expected)])

    def test_invalid_checked_catalog_fails_before_any_github_request(self):
        bad = list(load_catalog().targets)
        bad[-1] = type(bad[-1])("ocpp-simulator", "arthexis/ocpp-simulator",
                                 bad[-1].adapter_id, bad[-1].probe_id,
                                 bad[-1].release_mode)
        with patch.object(github_state, "load_catalog",
                          return_value=type("Catalog", (), {"targets": tuple(bad)})()), \
             patch.object(github_state, "main_head",
                          side_effect=AssertionError("network")) as head, \
             patch.object(github_state, "plan",
                          side_effect=AssertionError("policy")) as policy:
            with self.assertRaisesRegex(ValueError, "catalog differs"):
                github_state.report(self.client, now=NOW)
            head.assert_not_called()
            policy.assert_not_called()

    def test_bad_snapshot_in_collector_fails_closed_before_network(self):
        for value in (
            (), list(TARGETS), TARGETS[:-1], tuple(reversed(TARGETS)),
            TARGETS + (("ocpp-simulator", "arthexis/ocpp-simulator"),)
        ):
            with self.subTest(value=repr(value)[:80]), \
                 patch.object(github_state, "main_head",
                              side_effect=AssertionError("network")) as head, \
                 patch.object(github_state, "load_catalog",
                              side_effect=AssertionError("resource I/O")) as loader:
                with self.assertRaisesRegex(ValueError, "catalog differs"):
                    github_state.collect(self.client, catalog_targets=value)
                head.assert_not_called()
                loader.assert_not_called()

    def test_unknown_ci_does_not_create_attempts(self):
        with patch.object(github_state, "main_head", return_value=SHA), \
             patch.object(github_state, "main_arrival", return_value=ARRIVED), \
             patch.object(github_state, "ci_for_head", return_value="unknown"):
            result = github_state.report(self.client, now=NOW)
        self.assertEqual(result["decision"], "blocked")
        self.assertEqual(result["attempt"], [])
        self.assertTrue(all(row["ci"] == "unknown" for row in result["targets"]))

    def test_existing_direct_collect_call_still_loads_once(self):
        with patch.object(github_state, "load_catalog", wraps=load_catalog) as loader, \
             patch.object(github_state, "main_head", return_value=SHA), \
             patch.object(github_state, "main_arrival", return_value=ARRIVED), \
             patch.object(github_state, "ci_for_head", return_value="success"):
            states = github_state.collect(self.client)
        loader.assert_called_once_with()
        self.assertEqual(tuple(s.name for s in states),
                         tuple(name for name, _ in TARGETS))


if __name__ == "__main__":
    unittest.main()
