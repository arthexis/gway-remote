import unittest
from gway_remote.__main__ import validate


class WorkloadPolicyTests(unittest.TestCase):
    def test_health_no_input(self):
        validate("system-health")

    def test_health_rejects_payload(self):
        with self.assertRaises(ValueError):
            validate("system-health", "arthexis/ocpp-csms", "")

    def test_unknown_task(self):
        with self.assertRaises(ValueError):
            validate("arbitrary-command")

    def test_retired_simulator_tasks_are_denied(self):
        for task in ("ocpp-simulator", "ocpp-simulator-deploy"):
            with self.subTest(task=task), self.assertRaisesRegex(ValueError, "Unknown task"):
                validate(task, "arthexis/ocpp-simulator", "a" * 40)

    def test_allowed_csms(self):
        validate("ocpp-csms-deploy", "arthexis/ocpp-csms", "a" * 40)

    def test_repository_denied(self):
        with self.assertRaises(ValueError):
            validate("ocpp-csms-deploy", "evil/repo", "a" * 40)

    def test_mutable_ref_denied(self):
        with self.assertRaises(ValueError):
            validate("ocpp-csms-deploy", "arthexis/ocpp-csms", "main")


if __name__ == "__main__":
    unittest.main()
