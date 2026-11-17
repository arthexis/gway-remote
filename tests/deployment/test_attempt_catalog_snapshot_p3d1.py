"""#565 P3-D1: optional immutable catalog snapshot is a pure policy input."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from gway_remote import attempt_policy
from gway_remote.catalog_shadow import load_catalog
from gway_remote.reconcile import TARGETS


NOW = datetime(2026, 11, 17, 3, 0, tzinfo=timezone.utc)
SHA = "a" * 40
OLD = "b" * 40


class AttemptCatalogSnapshotP3D1Tests(unittest.TestCase):
    def candidates(self):
        return tuple(
            attempt_policy.Candidate(name, SHA, NOW - timedelta(minutes=20),
                                     "success", OLD)
            for name, _ in TARGETS
        )

    def checked(self):
        return tuple((t.id, t.repository) for t in load_catalog().targets)

    def test_exact_legacy_plan_and_seven_target_order(self):
        checked = self.checked()
        self.assertEqual(checked, TARGETS)
        baseline = self.candidates()
        old_plan = attempt_policy.plan(baseline, NOW)
        new_plan = attempt_policy.plan(baseline, NOW, catalog_targets=checked)
        self.assertEqual(new_plan, old_plan)
        self.assertEqual(
            new_plan.pending, tuple((name, SHA) for name, _ in TARGETS))

    def test_managed_subsets_deny_all_and_unknown_managed(self):
        checked = self.checked()
        names = {TARGETS[0][0], TARGETS[-1][0]}
        subset = tuple(c for c in self.candidates() if c.name in names)
        for managed, candidates in (
            (names, subset), (set(), ()), ({"ocpp-simulator"}, ())
        ):
            with self.subTest(managed=managed):
                self.assertEqual(
                    attempt_policy.plan(candidates, NOW, managed=managed),
                    attempt_policy.plan(candidates, NOW, managed=managed,
                                        catalog_targets=checked))

    def test_descriptor_drift_always_fails_closed(self):
        examples = (
            TARGETS[:-1],
            TARGETS + (("ocpp-simulator", "arthexis/ocpp-simulator"),),
            TARGETS[:-1] + (("ocpp-simulator", "arthexis/ocpp-simulator"),),
            tuple(reversed(TARGETS)),
            TARGETS[:-1] + ((TARGETS[-1][0], "arthexis/other"),),
            TARGETS[:-1] + (TARGETS[0],),
            (), list(TARGETS), "ocpp-csms", {},
        )
        for supplied in examples:
            with self.subTest(supplied=repr(supplied)[:70]):
                result = attempt_policy.plan(
                    self.candidates(), NOW, catalog_targets=supplied)
                self.assertEqual(result.state, "blocked")
                self.assertEqual(result.pending, ())
                self.assertEqual(
                    result.reason, "catalog differs from reviewed target registry")
        self.assertEqual(
            attempt_policy.plan(self.candidates(), NOW,
                                catalog_targets=TARGETS).state,
            "ready")

    def test_invalid_catalog_rejected_before_candidate_iteration(self):
        class CandidatesNotReadable:
            def __iter__(self):
                raise AssertionError("candidate read")
        with patch("gway_remote.catalog_shadow.load_catalog",
                   side_effect=AssertionError("catalog I/O")) as loader:
            with patch("subprocess.run",
                       side_effect=AssertionError("process I/O")) as process:
                result = attempt_policy.plan(
                    CandidatesNotReadable(), NOW, catalog_targets=(("x", "y"),))
                self.assertEqual(result.state, "blocked")
                loader.assert_not_called()
                process.assert_not_called()

    def test_valid_snapshot_does_not_load_catalog_or_spawn_processes(self):
        snapshot = self.checked()
        with patch("gway_remote.catalog_shadow.load_catalog",
                   side_effect=AssertionError("catalog I/O")) as loader:
            with patch("subprocess.run",
                       side_effect=AssertionError("process I/O")) as process:
                self.assertEqual(
                    attempt_policy.plan(self.candidates(), NOW,
                                        catalog_targets=snapshot).state,
                    "ready")
                loader.assert_not_called()
                process.assert_not_called()

    def test_ci_cooldown_retry_and_sha_guards_unchanged(self):
        baseline = self.candidates()
        unknown_ci = list(baseline)
        unknown_ci[0] = replace(unknown_ci[0], ci="unknown")
        done = tuple(replace(x, attempted_sha=SHA) for x in baseline)
        quiet = tuple(replace(x, merged_at=NOW) for x in baseline)
        bad_sha = list(baseline)
        bad_sha[0] = replace(bad_sha[0], sha="x" * 40)
        for rows in (tuple(unknown_ci), done, quiet, tuple(bad_sha)):
            with self.subTest(rows=rows[0]):
                self.assertEqual(
                    attempt_policy.plan(rows, NOW),
                    attempt_policy.plan(rows, NOW, catalog_targets=TARGETS))
        self.assertEqual(
            attempt_policy.plan(done, NOW, catalog_targets=TARGETS).state,
            "idle")
        self.assertEqual(
            attempt_policy.plan(quiet, NOW, catalog_targets=TARGETS).state,
            "waiting")
        self.assertEqual(
            attempt_policy.plan(tuple(unknown_ci), NOW,
                                catalog_targets=TARGETS).state,
            "blocked")


if __name__ == "__main__":
    unittest.main()
