"""Offline integration tests for appliance-wide reconciliation.

These tests exercise the real policy and executor, with fake GitHub state,
installation verification and deployment callbacks. No appliance is contacted.
"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gway_remote.execution import execute
from gway_remote.reconcile import Decision, TARGETS, TargetState


class FakeAppliance:
    def __init__(self, directory):
        self.now = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
        self.updated = self.now - timedelta(minutes=21)
        self.main = {name: "b" * 40 for name, _ in TARGETS}
        self.deployed = {name: "a" * 40 for name, _ in TARGETS}
        self.verified = set()
        self.events = []
        self.lock = Path(directory) / "appliance.lock"
        self.ci = {name: "success" for name, _ in TARGETS}
        self.fail_record = False

    def collect(self, client):
        return tuple(TargetState(name, self.main[name], self.deployed[name],
                                 self.updated, self.ci[name]) for name, _ in TARGETS)

    def verify(self, name, sha):
        return (name, sha) in self.verified

    def deploy(self, name, sha):
        self.events.append(("deploy", name))
        self.verified.add((name, sha))

    def record(self, name, sha):
        self.events.append(("record", name))
        if self.fail_record:
            self.fail_record = False
            raise RuntimeError("GitHub deployment write failed")
        self.deployed[name] = sha

    def run(self):
        return execute(None, self.collect, lambda: self.now, self.deploy,
                       self.verify, self.record, self.lock)


class ReconciliationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = FakeAppliance(self.tmp.name)

    def test_ordered_deploy_and_record(self):
        plan = self.app.run()
        self.assertEqual(plan.decision, Decision.READY)
        self.assertEqual(self.app.events, [
            (action, name) for name, _ in TARGETS for action in ("deploy", "record")
        ])

    def test_shared_quiet_period_blocks_all_targets(self):
        self.app.updated = self.app.now - timedelta(minutes=19)
        self.assertEqual(self.app.run().decision, Decision.WAITING)
        self.assertEqual(self.app.events, [])

    def test_failed_ci_blocks_all_targets(self):
        self.app.ci["gway-lcd-sound"] = "failure"
        self.assertEqual(self.app.run().decision, Decision.BLOCKED)
        self.assertEqual(self.app.events, [])

    def test_record_failure_retry_does_not_reinstall(self):
        self.app.fail_record = True
        with self.assertRaisesRegex(RuntimeError, "GitHub deployment"):
            self.app.run()
        self.assertEqual(self.app.events, [
            ("deploy", "ocpp-csms"), ("record", "ocpp-csms")
        ])
        self.app.events.clear()
        self.app.run()
        self.assertEqual(self.app.events[0], ("record", "ocpp-csms"))
        self.assertNotIn(("deploy", "ocpp-csms"), self.app.events)

    def test_stale_head_stops_after_first_target(self):
        original_record = self.app.record
        def record_and_change(name, sha):
            original_record(name, sha)
            self.app.main["gway-lcd-sound"] = "c" * 40
        self.app.record = record_and_change
        with self.assertRaisesRegex(RuntimeError, "stale"):
            self.app.run()
        self.assertEqual(self.app.events, [
            ("deploy", "ocpp-csms"), ("record", "ocpp-csms")
        ])

    def test_no_changes(self):
        self.app.deployed = dict(self.app.main)
        self.assertEqual(self.app.run().decision, Decision.UP_TO_DATE)
        self.assertEqual(self.app.events, [])


if __name__ == "__main__":
    unittest.main()
