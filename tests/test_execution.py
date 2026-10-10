"""Executor tests: ordering, failure, stale snapshot and exclusive lock."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gway_remote.execution import appliance_lock, execute
from gway_remote.reconcile import TARGETS, TargetState


class TestExecution(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.lock = Path(self.directory.name) / "lock"
        self.installed = {name: "a" * 40 for name, _ in TARGETS}
        self.desired = {name: "b" * 40 for name, _ in TARGETS}
        self.calls = []
        self.verified = set()
        self.now = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)

    def collect(self, client):
        return tuple(
            TargetState(name, self.desired[name], self.installed[name],
                        datetime(2026, 10, 9, 11, tzinfo=timezone.utc),
                        "success")
            for name, _ in TARGETS
        )

    def execute(self, *, verify=None, deploy=None):
        def default_deploy(name, sha):
            self.calls.append(("deploy", name))
            self.verified.add(name)
        def record(name, sha):
            self.calls.append(("record", name))
            self.installed[name] = sha
        return execute(
            None, self.collect, lambda: self.now,
            deploy or default_deploy,
            verify or (lambda name, sha: name in self.verified or self.installed[name] == sha),
            record, self.lock,
        )

    def test_deploys_in_order_and_records_after_each(self):
        self.execute()
        self.assertEqual(self.calls, [
            ("deploy", name) if index % 2 == 0 else ("record", name)
            for name, _ in TARGETS for index in (0, 1)
        ])

    def test_failed_verification_stops_without_record(self):
        with self.assertRaisesRegex(RuntimeError, "verification failed"):
            self.execute(verify=lambda name, sha: False)
        self.assertEqual(self.calls, [("deploy", "ocpp-csms")])

    def test_failed_deployment_stops_without_record(self):
        def fail(name, sha):
            self.calls.append(("deploy", name))
            self.verified.add(name)
            if name == "ocpp-simulator":
                raise RuntimeError("deploy failed")
        with self.assertRaisesRegex(RuntimeError, "deploy failed"):
            self.execute(deploy=fail)
        self.assertEqual(self.calls, [
            ("deploy", "ocpp-csms"), ("record", "ocpp-csms"),
            ("deploy", "ocpp-simulator"),
        ])

    def test_stale_snapshot_stops_before_next_target(self):
        def mutate(name, sha):
            self.calls.append(("deploy", name))
            self.verified.add(name)
            self.desired["gway-lcd-sound"] = "c" * 40
        with self.assertRaisesRegex(RuntimeError, "stale"):
            self.execute(deploy=mutate)
        self.assertEqual(self.calls, [
            ("deploy", "ocpp-csms"), ("record", "ocpp-csms"),
        ])

    def test_no_changes_does_nothing(self):
        self.installed = dict(self.desired)
        plan = self.execute()
        self.assertEqual(plan.decision.value, "up-to-date")
        self.assertEqual(self.calls, [])

    def test_exclusive_lock(self):
        with appliance_lock(self.lock):
            with self.assertRaisesRegex(RuntimeError, "already active"):
                self.execute()


if __name__ == "__main__":
    unittest.main()
