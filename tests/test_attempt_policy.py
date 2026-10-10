import unittest
from datetime import datetime, timedelta, timezone
from gway_remote.attempt_policy import Candidate, plan
from gway_remote.reconcile import TARGETS

NOW = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)


def candidates(attempted=False):
    return [Candidate(name, "a" * 40, NOW - timedelta(minutes=21),
                      "success", "a" * 40 if attempted else None)
            for name, _ in TARGETS]


class AttemptPolicyTests(unittest.TestCase):
    def test_first_attempt_without_bootstrap(self):
        result = plan(candidates(), NOW)
        self.assertEqual(result.state, "ready")
        self.assertEqual(len(result.pending), 3)

    def test_no_retries_for_attempted_sha(self):
        self.assertEqual(plan(candidates(True), NOW).state, "idle")

    def test_changed_revision_is_eligible(self):
        values = candidates(True)
        values[0] = Candidate(values[0].name, "b" * 40,
                              values[0].merged_at, "success", "a" * 40)
        self.assertEqual(plan(values, NOW).pending, ((values[0].name, "b" * 40),))

    def test_shared_quiet_period(self):
        values = candidates()
        values[2] = Candidate(values[2].name, values[2].sha,
                              NOW - timedelta(minutes=5), "success")
        self.assertEqual(plan(values, NOW).state, "waiting")

    def test_ci_failure_blocks(self):
        values = candidates()
        values[0] = Candidate(values[0].name, values[0].sha,
                              values[0].merged_at, "failure")
        self.assertEqual(plan(values, NOW).state, "blocked")


if __name__ == "__main__":
    unittest.main()
