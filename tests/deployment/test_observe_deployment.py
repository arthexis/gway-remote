"""B2: existing probe parity and fail-closed local observation."""
import json
import unittest
from unittest.mock import patch

from gway_remote.deployment_evidence import adapt_component
from gway_remote.observe_deployment import main, observe


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.evidence = adapt_component(
            {"name": "gway-lcd-sound", "installed_sha": "a" * 12,
             "health": "healthy"},
            observed_at="2026-11-08T10:00:00+00:00")
        self.report = {"components": [{"name": "gway-lcd-sound",
                                        "deployment_evidence": self.evidence}]}

    def test_exact_parity_with_existing_adapter(self):
        self.assertEqual(observe("gway-lcd-sound",
                                 allowed={"arthexis/gway-lcd-sound"}, report=self.report),
                         self.evidence)

    def test_denied_before_probing(self):
        with patch("gway_remote.observe_deployment.status") as probe:
            with self.assertRaises(ValueError):
                observe("gway-lcd-sound", allowed=set())
            with self.assertRaises(ValueError):
                observe("unregistered-component", allowed={"arthexis/unregistered-component"})
            probe.assert_not_called()

    def test_component_name_is_not_inventory_permission(self):
        with self.assertRaises(ValueError):
            observe("gway-lcd-sound", allowed={"gway-lcd-sound"}, report=self.report)

    def test_missing_or_duplicate_fails_closed(self):
        for rows in ([], self.report["components"] * 2):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                observe("gway-lcd-sound", allowed={"arthexis/gway-lcd-sound"},
                        report={"components": rows})

    def test_no_mutation_and_repeatability(self):
        before = json.dumps(self.report, sort_keys=True)
        for _ in range(2):
            self.assertEqual(observe("gway-lcd-sound",
                                     allowed={"arthexis/gway-lcd-sound"}, report=self.report),
                             self.evidence)
        self.assertEqual(json.dumps(self.report, sort_keys=True), before)

    def test_invalid_schema_is_rejected(self):
        corrupted = {"components": [{"name": "gway-lcd-sound",
                                      "deployment_evidence": {**self.evidence, "schema_version": 2}}]}
        with self.assertRaises(ValueError):
            observe("gway-lcd-sound", allowed={"arthexis/gway-lcd-sound"}, report=corrupted)

    def test_cli_uses_existing_inventory_authority(self):
        with patch("gway_remote.observe_deployment._node_policy", return_value=set()), \
             patch("gway_remote.observe_deployment.status") as probe:
            with self.assertRaises(ValueError):
                main(["--component", "gway-lcd-sound"])
            probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
