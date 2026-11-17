"""#565 P3-C2: policy and watcher admission guardrails; tests only.

These tests pin the current pure-policy and reservation contracts before any
migration from reconcile.TARGETS. They never dispatch, contact nodes, or use
GitHub. Real time is frozen and all journal paths are temporary.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gway_remote import appliance_watch, attempt_policy, reconcile
from gway_remote.catalog_shadow import load_catalog


NOW = datetime(2026, 11, 17, 2, 0, tzinfo=timezone.utc)
SHA = "a" * 40
OLD_SHA = "b" * 40


class PurePolicyCatalogP3C2Tests(unittest.TestCase):
    def setUp(self):
        self.names = tuple(name for name, _ in reconcile.TARGETS)

    def _attempts(self, **changes):
        candidates = [
            attempt_policy.Candidate(name, SHA, NOW - timedelta(minutes=20),
                                     "success", OLD_SHA)
            for name in self.names
        ]
        for i, row in enumerate(candidates):
            if row.name in changes:
                candidates[i] = replace(row, **changes[row.name])
        return tuple(candidates)

    def _reconcile(self, **changes):
        rows = [
            reconcile.TargetState(name, SHA, OLD_SHA,
                                  NOW - timedelta(minutes=20), "success")
            for name in self.names
        ]
        for i, row in enumerate(rows):
            if row.name in changes:
                rows[i] = replace(row, **changes[row.name])
        return tuple(rows)

    def test_checked_catalog_still_matches_immutable_seven(self):
        self.assertEqual(
            tuple((t.id, t.repository) for t in load_catalog().targets),
            reconcile.TARGETS,
        )
        self.assertEqual(len(self.names), 7)
        self.assertNotIn("ocpp-simulator", self.names)

    def test_attempt_policy_ready_order_and_managed_filter(self):
        result = attempt_policy.plan(self._attempts(), NOW)
        self.assertEqual((result.state, result.reason),
                         ("ready", "one best-effort attempt per pending revision"))
        self.assertEqual(result.pending, tuple((name, SHA) for name in self.names))
        selected = (self.names[0], self.names[-1])
        subset = tuple(c for c in self._attempts() if c.name in selected)
        filtered = attempt_policy.plan(subset, NOW, managed=set(selected))
        self.assertEqual(filtered.state, "ready")
        self.assertEqual(filtered.pending, tuple((name, SHA) for name in selected))
        self.assertEqual(attempt_policy.plan((), NOW, managed=set()).state, "idle")

    def test_attempt_policy_no_implicit_retry_or_unverified_ci(self):
        attempted = tuple(replace(c, attempted_sha=SHA) for c in self._attempts())
        self.assertEqual(attempt_policy.plan(attempted, NOW).state, "idle")
        broken_ci = list(self._attempts())
        broken_ci[0] = replace(broken_ci[0], ci="unknown")
        self.assertEqual(attempt_policy.plan(tuple(broken_ci), NOW).state, "blocked")
        premature = tuple(replace(c, merged_at=NOW) for c in self._attempts())
        self.assertEqual(attempt_policy.plan(premature, NOW).state, "waiting")
        self.assertEqual(attempt_policy.plan(premature, NOW, bypass_quiet=True).state,
                         "ready")

    def test_attempt_policy_denies_missing_extra_duplicate_or_invalid(self):
        baseline = self._attempts()
        for rows in (
            baseline[:-1],
            baseline + (baseline[0],),
            baseline[:-1] + (replace(baseline[-1], name="ocpp-simulator"),),
        ):
            with self.subTest(rows=len(rows)):
                self.assertEqual(attempt_policy.plan(rows, NOW).state, "blocked")
        wrong_sha = list(baseline)
        wrong_sha[0] = replace(wrong_sha[0], sha="x" * 40)
        self.assertEqual(attempt_policy.plan(tuple(wrong_sha), NOW).state, "blocked")
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            attempt_policy.plan(baseline, NOW.replace(tzinfo=None))

    def test_reconcile_requires_full_verified_snapshot(self):
        rows = self._reconcile()
        plan = reconcile.reconcile(rows, NOW)
        self.assertEqual(plan.decision, reconcile.Decision.READY)
        self.assertEqual(
            tuple((x.name, x.sha) for x in plan.targets),
            tuple((name, SHA) for name in self.names),
        )
        self.assertEqual(
            tuple((x.name, x.sha) for x in plan.desired_revisions),
            tuple((name, SHA) for name in self.names),
        )
        for bad in (
            rows[:-1],
            rows + (rows[0],),
            rows[:-1] + (replace(rows[-1], name="ocpp-simulator"),),
        ):
            self.assertEqual(reconcile.reconcile(bad, NOW).decision,
                             reconcile.Decision.BLOCKED)
        self.assertEqual(reconcile.reconcile(
            self._reconcile(**{self.names[0]: {"deployed_sha": None}}), NOW
        ).decision, reconcile.Decision.BLOCKED)
        self.assertEqual(reconcile.reconcile(
            self._reconcile(**{self.names[0]: {"ci_status": "pending"}}), NOW
        ).decision, reconcile.Decision.BLOCKED)

    def test_reconcile_waiting_current_and_no_unproven_health(self):
        self.assertEqual(reconcile.reconcile(
            self._reconcile(**{self.names[0]: {"main_updated_at": NOW}}), NOW
        ).decision, reconcile.Decision.WAITING)
        current = tuple(replace(x, deployed_sha=SHA) for x in self._reconcile())
        result = reconcile.reconcile(current, NOW)
        self.assertEqual(result.decision, reconcile.Decision.UP_TO_DATE)
        self.assertEqual(result.targets, ())
        self.assertEqual(reconcile.reconcile(
            self._reconcile(**{self.names[0]: {"desired_sha": "z" * 40}}), NOW
        ).decision, reconcile.Decision.BLOCKED)

    def test_policy_calls_remain_pure_and_do_not_load_catalog(self):
        with patch("gway_remote.catalog_shadow.load_catalog",
                   side_effect=AssertionError("runtime catalog I/O")) as loader, \
             patch("subprocess.run",
                   side_effect=AssertionError("process I/O")) as process:
            attempt_policy.plan(self._attempts(), NOW)
            reconcile.reconcile(self._reconcile(), NOW)
            loader.assert_not_called()
            process.assert_not_called()


class WatcherGuardrailsP3C2Tests(unittest.TestCase):
    def test_unknown_or_unverified_revision_never_implies_missing(self):
        row = {"name": "ocpp-csms", "revision_status": "unknown",
               "installed_sha": None}
        self.assertFalse(appliance_watch.missing_installation(
            row, {"health": "unknown", "systemd": {}}, "executable-missing"))
        self.assertFalse(appliance_watch.eligible(
            {"revision_status": "unknown", "attempted_sha": None,
             "attempt_status": "never-attempted", "latest_sha": SHA},
            "success", NOW - timedelta(hours=1), NOW))

    def test_eligibility_requires_ci_cooldown_and_no_prior_attempt(self):
        row = {"revision_status": "behind", "attempted_sha": OLD_SHA,
               "attempt_status": "failed", "latest_sha": SHA}
        self.assertTrue(appliance_watch.eligible(
            row, "success", NOW - timedelta(minutes=20), NOW))
        for ci, merged, attempted in (
            ("unknown", NOW - timedelta(minutes=20), OLD_SHA),
            ("success", NOW - timedelta(minutes=5), OLD_SHA),
            ("success", None, OLD_SHA),
            ("success", NOW - timedelta(minutes=20), SHA),
        ):
            with self.subTest(ci=ci, merged=merged, attempted=attempted):
                self.assertFalse(appliance_watch.eligible(
                    {**row, "attempted_sha": attempted}, ci, merged, NOW))

    def test_reservations_reject_unknown_names_and_malformed_sha(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / "watch-dispatches.json"
            self.assertEqual(appliance_watch._dispatch_reservations(td), {})
            for data in (
                {"ocpp-simulator": SHA},
                {"ocpp-csms": "A" * 40},
                {"ocpp-csms": "x" * 40},
                {"ocpp-csms": 0},
                {"ocpp-csms": SHA, "extra-target": OLD_SHA},
            ):
                file.write_text(json.dumps(data), encoding="utf-8")
                with self.subTest(data=data), self.assertRaises(ValueError):
                    appliance_watch._dispatch_reservations(td)
            good = {"ocpp-csms": SHA}
            file.write_text(json.dumps(good), encoding="utf-8")
            self.assertEqual(appliance_watch._dispatch_reservations(td), good)

    def test_watch_policy_guardrails_do_not_dispatch_or_write(self):
        with patch.object(appliance_watch, "dispatch",
                          side_effect=AssertionError("dispatch")) as dispatch, \
             patch.object(appliance_watch, "_issue",
                          side_effect=AssertionError("issue write")) as issue:
            self.test_unknown_or_unverified_revision_never_implies_missing()
            self.test_eligibility_requires_ci_cooldown_and_no_prior_attempt()
            dispatch.assert_not_called()
            issue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
