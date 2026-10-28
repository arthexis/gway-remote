"""Contract fixtures for all registered deployment targets."""
import unittest

from gway_remote.deployment_evidence import adapt_component
from gway_remote.reconcile import TARGETS


class EvidenceContractTests(unittest.TestCase):
    def row(self, name, **overrides):
        value = dict(name=name, attempted_sha="a" * 40, installed_sha=None,
                     staged_sha=None, release_state=None, health="unknown",
                     evidence=None, installation="installed")
        value.update(overrides)
        return value

    def adapt(self, name, **overrides):
        return adapt_component(self.row(name, **overrides),
                               observed_at="2026-10-28T00:00:00+00:00")

    def test_all_catalog_targets_have_safe_envelopes(self):
        for name, repository in TARGETS:
            with self.subTest(name=name):
                result = self.adapt(name)
                self.assertEqual(result["schema_version"], 1)
                self.assertEqual(result["repository"], repository)
                self.assertEqual(result["installation_state"], "unknown")
                self.assertIsNone(result["activated_revision"])
                self.assertNotEqual(result["runtime_state"], "healthy")

    def test_attempt_success_does_not_prove_activation(self):
        row = self.adapt("ocpp-csms", installation="installed")
        self.assertEqual(row["installation_state"], "unknown")
        self.assertIsNone(row["source_revision"])

    def test_verified_active_symlink_and_independent_runtime(self):
        row = self.adapt("ocpp-csms", installed_sha="b" * 12, health="unhealthy")
        self.assertEqual(row["installation_state"], "activated")
        self.assertEqual(row["activated_revision"], "b" * 12)
        self.assertEqual(row["runtime_state"], "unhealthy")

    def test_revision_file_alone_is_not_activation(self):
        row = self.adapt("gway-ap-kiosk", installed_sha="b" * 40)
        self.assertEqual(row["installation_state"], "unknown")
        self.assertIsNone(row["activated_revision"])

    def test_bastion_staged_only(self):
        row = self.adapt("gway-bastion", staged_sha="b" * 40,
                         release_state="staged", health="not_applicable")
        self.assertEqual(row["installation_state"], "staged")
        self.assertEqual(row["runtime_state"], "not_applicable")

    def test_bastion_activated_without_health_probe(self):
        row = self.adapt("gway-bastion", installed_sha="b" * 40,
                         release_state="activated", health="healthy")
        self.assertEqual(row["installation_state"], "activated")
        self.assertEqual(row["runtime_state"], "unknown")

    def test_invalid_bastion_fails_closed(self):
        row = self.adapt("gway-bastion", evidence="invalid", health="healthy")
        self.assertEqual(row["installation_state"], "unknown")
        self.assertEqual(row["runtime_state"], "unknown")
        self.assertTrue(row["errors"])

    def test_cli_only_runtime_not_applicable(self):
        row = self.adapt("ocpp-simulator", installed_sha="b" * 12,
                         health="healthy")
        self.assertEqual(row["runtime_state"], "not_applicable")

    def test_quick_probe_cannot_claim_health(self):
        row = adapt_component(self.row("ocpp-csms", installed_sha="b" * 12,
                                       health="healthy"), observed_at=None, depth="quick")
        self.assertEqual(row["runtime_state"], "unknown")
        self.assertIsNone(row["observed_at"])


if __name__ == "__main__":
    unittest.main()
