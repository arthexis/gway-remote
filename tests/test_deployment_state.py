import unittest
from gway_remote.deployment_state import bootstrap_audit
from gway_remote.reconcile import TARGETS, TargetState


class TestBootstrapAudit(unittest.TestCase):
    def test_unknown_installation_requires_verification(self):
        states = tuple(TargetState(name, "a" * 40, None, None, "unknown")
                       for name, _ in TARGETS)
        audit = bootstrap_audit(states)
        self.assertEqual(len(audit), 3)
        self.assertTrue(all(item.status == "verification-required" for item in audit))
        self.assertTrue(all(item.installed_sha is None for item in audit))

    def test_existing_record_is_not_claimed_runtime_verified(self):
        states = tuple(TargetState(name, "a" * 40, "b" * 40, None, "success")
                       for name, _ in TARGETS)
        audit = bootstrap_audit(states)
        self.assertTrue(all(item.status == "recorded" for item in audit))
        self.assertTrue(all("separate" in item.reason for item in audit))


if __name__ == "__main__":
    unittest.main()
