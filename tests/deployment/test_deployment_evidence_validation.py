"""Validate the single existing v1 deployment evidence envelope."""
import unittest

from gway_remote.deployment_evidence import adapt_component, from_legacy, recovery_strategy, validate

SHA = "a" * 40


class EvidenceValidationTests(unittest.TestCase):
    def test_existing_adapter_parity(self):
        row = {"name": "ocpp-csms", "installed_sha": SHA, "health": "unhealthy"}
        original = adapt_component(row, observed_at="2026-11-08T10:00:00+00:00")
        self.assertEqual(validate(original), original)
        self.assertEqual(original["activated_revision"], SHA)

    def test_attempt_never_certifies_activation(self):
        row = from_legacy("ocpp-csms", attempt={"sha": SHA, "status": "installed"})
        self.assertIsNone(row["activated_revision"])
        self.assertEqual(row["runtime_state"], "unknown")
        self.assertIsNone(row["source_revision"])

    def test_bastion_staging(self):
        row = from_legacy("gway-bastion", bastion={"staged_sha": SHA})
        self.assertEqual(row["staged_revision"], SHA)
        self.assertIsNone(row["activated_revision"])
        self.assertEqual(row["installation_state"], "staged")

    def test_fail_forward_and_rollback(self):
        self.assertEqual(recovery_strategy("ocpp-csms"), "rollback")
        self.assertEqual(recovery_strategy("gway-remote"), "rollback")
        for name in ("gway-rfid", "gway-bastion", "ocpp-reports", "ocpp-simulator"):
            self.assertEqual(recovery_strategy(name), "fail_forward")

    def test_invalid_input(self):
        for attempt in ({"sha": "bad", "status": "installed"},
                        {"sha": SHA, "status": "invalid"}, []):
            with self.subTest(attempt=attempt), self.assertRaises(ValueError):
                from_legacy("gway-rfid", attempt=attempt)
        row = from_legacy("gway-rfid")
        row["observed_at"] = "2026-11-08T10:00:00"
        with self.assertRaises(ValueError):
            validate(row)
        row["observed_at"] = None
        row["schema_version"] = 2
        with self.assertRaises(ValueError):
            validate(row)

    def test_defensive_copy(self):
        row = from_legacy("gway-rfid")
        clone = validate(row)
        self.assertIsNot(row, clone)
        self.assertIsNot(row["capabilities"], clone["capabilities"])


if __name__ == "__main__":
    unittest.main()
