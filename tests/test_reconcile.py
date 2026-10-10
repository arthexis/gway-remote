"""Pure reconciliation policy tests (standard-library unittest)."""
import unittest
from datetime import datetime, timedelta, timezone
from gway_remote.reconcile import Decision, TARGETS, TargetState, reconcile

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
A, B = "a" * 40, "b" * 40


def states(changed=("ocpp-csms",), age=20, ci="success"):
    return tuple(TargetState(name, B if name in changed else A, A,
                             NOW - timedelta(minutes=age), ci)
                 for name, _ in TARGETS)


class TestReconcile(unittest.TestCase):
    def test_up_to_date(self):
        self.assertEqual(reconcile(states(changed=(), age=0), NOW).decision, Decision.UP_TO_DATE)

    def test_waiting(self):
        for age in (0, 5, 19.999):
            self.assertEqual(reconcile(states(age=age), NOW).decision, Decision.WAITING)

    def test_boundary_and_order(self):
        p = reconcile(states(changed=("ocpp-csms", "gway-lcd-sound")), NOW)
        self.assertEqual(p.decision, Decision.READY)
        self.assertEqual([t.name for t in p.targets], ["ocpp-csms", "gway-lcd-sound"])
        self.assertEqual(len(p.desired_revisions), 3)

    def test_any_repo_resets_deadline(self):
        s = list(states(age=30))
        s[1] = TargetState(s[1].name, A, A, NOW - timedelta(minutes=5), "success")
        p = reconcile(s, NOW)
        self.assertEqual(p.decision, Decision.WAITING)
        self.assertEqual(p.quiet_until, NOW + timedelta(minutes=15))

    def test_ci_fail_closed(self):
        for status in ("failure", "pending", "unknown", ""):
            self.assertEqual(reconcile(states(ci=status), NOW).decision, Decision.BLOCKED)

    def test_unchanged_ci_not_required(self):
        s = list(states())
        s[1] = TargetState(s[1].name, A, A, s[1].main_updated_at, "failure")
        self.assertEqual(reconcile(s, NOW).decision, Decision.READY)

    def test_unknown_state_and_invalid_sha(self):
        for sha, deployed, updated in ((B, None, NOW), ("bad", A, NOW), (B, A, None)):
            s = list(states())
            s[0] = TargetState(s[0].name, sha, deployed, updated, "success")
            self.assertEqual(reconcile(s, NOW).decision, Decision.BLOCKED)

    def test_target_set(self):
        s = states()
        self.assertEqual(reconcile(s[:-1], NOW).decision, Decision.BLOCKED)
        self.assertEqual(reconcile(s + (s[0],), NOW).decision, Decision.BLOCKED)

    def test_timezones_and_future(self):
        tz = timezone(timedelta(hours=-6))
        s = tuple(TargetState(t.name, t.desired_sha, t.deployed_sha,
                              t.main_updated_at.astimezone(tz), t.ci_status)
                  for t in states())
        self.assertEqual(reconcile(s, NOW).decision, Decision.READY)
        s = list(states())
        s[0] = TargetState(s[0].name, B, A, NOW + timedelta(minutes=1), "success")
        self.assertEqual(reconcile(s, NOW).decision, Decision.BLOCKED)
        with self.assertRaises(ValueError):
            reconcile(states(), NOW.replace(tzinfo=None))


if __name__ == "__main__":
    unittest.main()
