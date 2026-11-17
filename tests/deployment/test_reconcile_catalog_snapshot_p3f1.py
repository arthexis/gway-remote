"""#565 P3-F1: pure reconcile policy accepts only the exact reviewed snapshot.

All tests are hermetic; catalog loading is explicitly outside this policy.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from gway_remote import reconcile
from gway_remote.catalog_shadow import load_catalog


NOW = datetime(2026, 11, 17, 5, 0, tzinfo=timezone.utc)
SHA = "a" * 40
OLD = "b" * 40


class ReconcileCatalogSnapshotP3F1Tests(unittest.TestCase):
    def checked(self):
        return tuple((target.id, target.repository)
                     for target in load_catalog().targets)

    def states(self):
        return tuple(
            reconcile.TargetState(name, SHA, OLD,
                                  NOW - timedelta(minutes=20), "success")
            for name, _ in reconcile.TARGETS
        )

    def changed(self, states, *, index=0, **fields):
        result = list(states)
        result[index] = replace(result[index], **fields)
        return tuple(result)

    def test_exact_seven_order_and_ready_parity(self):
        snapshot = self.checked()
        self.assertEqual(snapshot, reconcile.TARGETS)
        rows = self.states()
        baseline = reconcile.reconcile(rows, NOW)
        result = reconcile.reconcile(rows, NOW, catalog_targets=snapshot)
        self.assertEqual(result, baseline)
        self.assertEqual(result.decision, reconcile.Decision.READY)
        self.assertEqual(
            result.targets,
            tuple(reconcile.DeploymentTarget(name, SHA)
                  for name, _ in reconcile.TARGETS))
        self.assertEqual(result.desired_revisions, result.targets)
        self.assertEqual(result.quiet_until, NOW - timedelta(minutes=10))

    def test_legacy_parity_for_every_decision_and_block_reason(self):
        rows = self.states()
        complete = tuple(replace(x, deployed_sha=SHA) for x in rows)
        scenarios = {
            "ready": rows,
            "waiting": self.changed(
                rows, main_updated_at=NOW - timedelta(minutes=5)),
            "up_to_date": complete,
            "up_to_date_even_without_new_ci": self.changed(
                complete, ci_status="pending"),
            "unverified_ci": self.changed(rows, ci_status="unknown"),
            "failed_ci": self.changed(rows, ci_status="failure"),
            "unknown_deployed_sha": self.changed(rows, deployed_sha=None),
            "invalid_desired_sha": self.changed(rows, desired_sha="z" * 40),
            "invalid_installed_sha": self.changed(rows, deployed_sha="z" * 40),
            "missing_timestamp": self.changed(rows, main_updated_at=None),
            "naive_timestamp": self.changed(
                rows, main_updated_at=NOW.replace(tzinfo=None)),
            "future_timestamp": self.changed(
                rows, main_updated_at=NOW + timedelta(seconds=1)),
            "missing_row": rows[:-1],
            "duplicate_row": rows + (rows[0],),
            "extra_simulator": rows + (
                reconcile.TargetState(
                    "ocpp-simulator", SHA, OLD,
                    NOW - timedelta(minutes=20), "success"),),
        }
        for title, case in scenarios.items():
            with self.subTest(title=title):
                self.assertEqual(
                    reconcile.reconcile(case, NOW),
                    reconcile.reconcile(
                        case, NOW, catalog_targets=reconcile.TARGETS))

    def test_input_order_not_deployment_order(self):
        rows = tuple(reversed(self.states()))
        old_result = reconcile.reconcile(rows, NOW)
        new_result = reconcile.reconcile(
            rows, NOW, catalog_targets=reconcile.TARGETS)
        self.assertEqual(new_result, old_result)
        self.assertEqual(
            tuple(item.name for item in new_result.targets),
            tuple(name for name, _ in reconcile.TARGETS))

    def test_timestamp_offsets_and_exact_quiet_boundary(self):
        rows = self.states()
        offset = timezone(timedelta(hours=-6))
        shifted = NOW.astimezone(offset)
        recent = self.changed(
            rows, main_updated_at=NOW - timedelta(minutes=10))
        for clock in (NOW, shifted):
            with self.subTest(clock=clock):
                self.assertEqual(
                    reconcile.reconcile(
                        recent, clock, catalog_targets=reconcile.TARGETS),
                    reconcile.reconcile(recent, clock))
                self.assertEqual(
                    reconcile.reconcile(
                        recent, clock, catalog_targets=reconcile.TARGETS
                    ).decision,
                    reconcile.Decision.READY)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            reconcile.reconcile(
                rows, NOW.replace(tzinfo=None),
                catalog_targets=reconcile.TARGETS)

    def test_missing_duplicate_reordered_and_extra_catalog_fail_closed(self):
        registry = reconcile.TARGETS
        bad = (
            (),
            registry[:-1],
            registry + (registry[0],),
            registry + (("ocpp-simulator", "arthexis/ocpp-simulator"),),
            registry[:-1] + (("ocpp-simulator", "arthexis/ocpp-simulator"),),
            registry[:-1] + ((registry[-1][0], "arthexis/other"),),
            tuple(reversed(registry)),
            registry[:-1] + (registry[0],),
            list(registry),
            dict(registry),
            "ocpp-csms",
            {registry[0]},
        )
        class TupleSubclass(tuple):
            pass
        for sample in (*bad, TupleSubclass(registry)):
            with self.subTest(snapshot=repr(sample)[:100]):
                plan = reconcile.reconcile(
                    self.states(), NOW, catalog_targets=sample)
                self.assertEqual(plan.decision, reconcile.Decision.BLOCKED)
                self.assertEqual(plan.targets, ())
                self.assertEqual(plan.desired_revisions, ())
                self.assertIsNone(plan.quiet_until)
                self.assertEqual(
                    plan.reason,
                    "catalog differs from reviewed target registry")

    def test_invalid_catalog_rejected_before_target_iteration(self):
        class ExplodingStates:
            def __iter__(self):
                raise AssertionError("input states must not be read")

        plan = reconcile.reconcile(
            ExplodingStates(), NOW, catalog_targets=())
        self.assertEqual(plan.decision, reconcile.Decision.BLOCKED)
        self.assertEqual(plan.targets, ())
        self.assertEqual(plan.desired_revisions, ())

    def test_missing_catalog_argument_keeps_legacy_path(self):
        for rows in (self.states(),
                     tuple(replace(x, deployed_sha=SHA)
                           for x in self.states())):
            with self.subTest(first=rows[0].deployed_sha):
                self.assertEqual(
                    reconcile.reconcile(rows, NOW),
                    reconcile.reconcile(rows, NOW, catalog_targets=None))

    def test_pure_policy_does_not_read_catalog_or_spawn_processes(self):
        checked = self.checked()
        with patch("gway_remote.catalog_shadow.load_catalog",
                   side_effect=AssertionError("catalog I/O")) as loader, \
             patch("subprocess.run",
                   side_effect=AssertionError("process I/O")) as process, \
             patch("urllib.request.urlopen",
                   side_effect=AssertionError("network I/O")) as network:
            self.assertEqual(
                reconcile.reconcile(
                    self.states(), NOW, catalog_targets=checked
                ).decision,
                reconcile.Decision.READY)
            self.assertEqual(
                reconcile.reconcile(
                    self.states(), NOW, catalog_targets=()
                ).decision,
                reconcile.Decision.BLOCKED)
            loader.assert_not_called()
            process.assert_not_called()
            network.assert_not_called()

    def test_catalog_descriptor_never_grants_known_extra_repo(self):
        attempted = self.states() + (
            reconcile.TargetState(
                "ocpp-simulator", SHA, OLD,
                NOW - timedelta(minutes=20), "success"),)
        result = reconcile.reconcile(
            attempted, NOW, catalog_targets=reconcile.TARGETS)
        self.assertEqual(result.decision, reconcile.Decision.BLOCKED)
        self.assertEqual(result.targets, ())


if __name__ == "__main__":
    unittest.main()
