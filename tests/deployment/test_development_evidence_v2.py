"""Hermetic V2 evidence adapters: no filesystem, network or node access."""
import copy
import unittest

from gway_remote.development_evidence_v2 import development_evidence_v2
from gway_remote.reconcile import TARGETS

SHA = "a" * 40
OTHER = "b" * 40
NOW = "2026-11-18T21:00:00Z"
REPO = "arthexis/ocpp-csms"


def fixture():
    result = {
        "name": "ocpp-csms",
        "journal": {"ocpp-csms": {
            "sha": SHA, "status": "installed", "at": "2026-11-18T20:00:00Z",
            "log": "private-token.log", "error": "Bearer private-secret"}},
        "status_report": {
            "schema": "gway-remote/status/v1", "depth": "deep", "node": "gway-001",
            "checked_at": NOW, "components": [{
                "name": "ocpp-csms", "installed_sha": SHA, "health": "healthy",
                "deployment_evidence": {
                    "schema_version": 1, "repository": REPO,
                    "source_revision": None, "staged_revision": None,
                    "activated_revision": SHA, "activated_at": "2026-11-18T20:59:59Z",
                    "observed_at": NOW, "installation_state": "activated",
                    "runtime_state": "healthy",
                    "evidence": ["verified_active_release"], "errors": [],
                    "capabilities": {
                        "staging": False, "activation": True,
                        "runtime_probe": True, "runtime_required": True,
                    },
                },
            }],
        },
        "github": {
            "repository": REPO, "head_sha": SHA, "ci_head_sha": SHA,
            "ci": "success", "head_observed_at": NOW, "ci_observed_at": NOW,
        },
        "observed_at": NOW, "now": NOW,
    }
    # Deep status lists the complete reviewed registry, even when a snapshot
    # projects a single component. Other rows must not masquerade as the target.
    result["status_report"]["components"].extend(
        {"name": target} for target, _ in TARGETS if target != "ocpp-csms"
    )
    return result


class V2EvidenceTests(unittest.TestCase):
    def test_consistent_values_still_are_not_attested_or_accepted(self):
        result = development_evidence_v2(**fixture())
        self.assertEqual(result["stage"], "review")
        self.assertEqual(result["functional_acceptance"], "unknown")
        self.assertEqual(result["source_attestation"], "unverified")
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["receipt"]["acceptance"], "unknown")
        self.assertEqual(result["sources"]["release"]["node"], "gway-001")
        self.assertEqual(result["sources"]["ci"]["source"], "github/pr-ci")
        self.assertNotIn("private-token", repr(result))
        self.assertNotIn("private-secret", repr(result))

    def test_staleness_per_source_and_clock_skew(self):
        value = fixture()
        value["github"]["ci_observed_at"] = "2026-11-18T20:59:00Z"
        good = development_evidence_v2(**value,
            max_age_seconds={"journal": 300, "release": 300, "github": 300, "ci": 61})
        self.assertEqual(good["stage"], "review")
        value["github"]["ci_observed_at"] = "2026-11-18T20:58:58Z"
        stale = development_evidence_v2(**value,
            max_age_seconds={"journal": 300, "release": 300, "github": 300, "ci": 61})
        self.assertEqual(stale["stage"], "unknown")
        self.assertEqual(stale["sources"]["ci"]["freshness"], "stale")
        value["github"]["ci_observed_at"] = "2026-11-18T21:00:01Z"
        self.assertEqual(development_evidence_v2(**value)["sources"]["ci"]["freshness"], "future")

    def test_short_sha_not_equal_full_release(self):
        value = fixture()
        item = value["status_report"]["components"][0]
        item["installed_sha"] = SHA[:12]
        item["deployment_evidence"]["activated_revision"] = SHA[:12]
        result = development_evidence_v2(**value)
        self.assertIsNone(result["installed_sha"])
        self.assertIn("installed_revision_not_full_sha", result["reasons"])
        self.assertNotEqual(result["stage"], "review")

    def test_staged_unhealthy_and_mismatched_release(self):
        for mutation, expected in (
            (lambda x: x["status_report"]["components"][0]["deployment_evidence"].update(installation_state="staged"),
             "activation_unverified"),
            (lambda x: x["status_report"]["components"][0].update(health="unhealthy"),
             "runtime_health_unverified"),
            (lambda x: x["status_report"]["components"][0].update(installed_sha=OTHER),
             "installed_revision_differs"),
        ):
            value = fixture()
            mutation(value)
            self.assertIn(expected, development_evidence_v2(**value)["reasons"])

    def test_wrong_node_wrong_repository_bad_depth_duplicate_rows(self):
        for mutation in (
            lambda x: x["status_report"].update(node="gway-002"),
            lambda x: x["status_report"].update(depth="quick"),
            lambda x: x["status_report"]["components"][0]["deployment_evidence"].update(repository="other/repo"),
            lambda x: x["github"].update(repository="other/repo"),
            lambda x: x["status_report"]["components"].append(copy.deepcopy(x["status_report"]["components"][0])),
        ):
            value = fixture()
            mutation(value)
            with self.assertRaises(ValueError):
                development_evidence_v2(**value)

    def test_partial_or_injected_inventory_fails_closed(self):
        for mutation in (
            lambda rows: rows.pop(),
            lambda rows: rows.append({"name": "unreviewed-node"}),
            lambda rows: rows.__setitem__(-1, {"name": "ocpp-csms"}),
        ):
            value = fixture()
            mutation(value["status_report"]["components"])
            with self.assertRaises(ValueError):
                development_evidence_v2(**value)

    def test_ci_bound_to_exact_head_and_unknown_status(self):
        value = fixture()
        value["github"]["ci_head_sha"] = OTHER
        self.assertIn("ci_revision_mismatch", development_evidence_v2(**value)["reasons"])
        value["github"]["ci_head_sha"] = SHA
        value["github"]["ci"] = "unknown"
        self.assertIn("ci_not_successful", development_evidence_v2(**value)["reasons"])

    def test_missing_attempt_or_broken_timestamps(self):
        value = fixture()
        value["journal"] = {}
        result = development_evidence_v2(**value)
        self.assertIsNone(result["receipt"])
        self.assertIn("attempt_unknown", result["reasons"])
        for bad in ("invalid", "2026-11-18T21:00:00", None):
            value = fixture()
            value["status_report"]["checked_at"] = bad
            value["status_report"]["components"][0]["deployment_evidence"]["observed_at"] = bad
            with self.assertRaises(ValueError):
                development_evidence_v2(**value)

    def test_freshness_policy_invalid_closed(self):
        for policy in ({"ci": 60}, {"journal": 1, "release": 1, "github": 1, "ci": 0},
                       {"journal": 1, "release": 1, "github": 1, "ci": True}):
            with self.assertRaises(ValueError):
                development_evidence_v2(**fixture(), max_age_seconds=policy)

    def test_failed_started_or_staged_attempt_never_reviews(self):
        for status in ("failed", "started", "staged"):
            value = fixture()
            value["journal"]["ocpp-csms"]["status"] = status
            result = development_evidence_v2(**value)
            self.assertEqual(result["stage"], "unknown")
            self.assertIn("attempt_not_installed", result["reasons"])

    def test_partial_or_contradictory_release_envelope(self):
        for mutation, expected in (
            (lambda x: x.pop("errors"), None),
            (lambda x: x.update(errors=["invalid_release_evidence"]), "invalid_release_evidence"),
            (lambda x: x.update(evidence=[]), "activation_unverified"),
            (lambda x: x["capabilities"].update(activation=False), "activation_unverified"),
            (lambda x: x.update(activated_at="2026-11-18T21:00:01Z"),
             "activation_after_release_read"),
        ):
            value = fixture()
            evidence = value["status_report"]["components"][0]["deployment_evidence"]
            mutation(evidence)
            if expected is None:
                with self.assertRaises(ValueError):
                    development_evidence_v2(**value)
            else:
                result = development_evidence_v2(**value)
                self.assertIn(expected, result["reasons"])
                self.assertEqual(result["stage"], "unknown")

    def test_attempt_timestamp_cannot_postdate_journal_read(self):
        value = fixture()
        value["journal"]["ocpp-csms"]["at"] = "2026-11-18T21:00:01Z"
        result = development_evidence_v2(**value)
        self.assertIn("attempt_after_journal_read", result["reasons"])
        self.assertEqual(result["stage"], "unknown")

    def test_journal_does_not_supply_installation(self):
        value = fixture()
        item = value["status_report"]["components"][0]
        item["installed_sha"] = None
        item["deployment_evidence"]["activated_revision"] = None
        item["deployment_evidence"]["installation_state"] = "unknown"
        result = development_evidence_v2(**value)
        self.assertIsNone(result["installed_sha"])
        self.assertIn("installed_revision_unknown", result["reasons"])
        self.assertEqual(result["receipt"]["requested_sha"], SHA)


if __name__ == "__main__":
    unittest.main()
