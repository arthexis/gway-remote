"""Hermetic evidence projections; no host, network or deployment access."""
import unittest

from gway_remote.development_evidence import deployment_receipt, development_snapshot

SHA = "a" * 40
OTHER = "b" * 40
ATTEMPT = {"sha": SHA, "status": "installed", "at": "2026-11-18T12:00:00Z",
           "log": "private.log", "error": "must not be exposed"}


class DevelopmentEvidenceTests(unittest.TestCase):
    def receipt(self, **kwargs):
        return deployment_receipt("ocpp-csms", ATTEMPT, **kwargs)

    def test_unknown_without_independent_probe(self):
        receipt = self.receipt()
        self.assertEqual(receipt["acceptance"], "unknown")
        self.assertIsNone(receipt["installed_sha"])
        self.assertEqual(receipt["release_match"], "unknown")
        self.assertNotIn("log", receipt)
        self.assertNotIn("error", receipt)

    def test_verified_requires_observed_sha_and_health(self):
        receipt = self.receipt(observed_sha=SHA.upper(), health="healthy")
        self.assertEqual(receipt["evidence"], "consistent")
        self.assertEqual(receipt["acceptance"], "unknown")
        self.assertEqual(receipt["installed_sha"], SHA)
        self.assertEqual(receipt["attempt_at"], "2026-11-18T12:00:00+00:00")
        for kwargs in ({"observed_sha": OTHER, "health": "healthy"},
                       {"observed_sha": SHA, "health": "unhealthy"},
                       {"observed_sha": SHA}):
            self.assertEqual(self.receipt(**kwargs)["acceptance"], "unknown")

    def test_staged_never_becomes_installed(self):
        attempt = dict(ATTEMPT, status="staged")
        receipt = deployment_receipt("gway-bastion", attempt,
                                     observed_sha=SHA, health="healthy")
        self.assertEqual(receipt["acceptance"], "unknown")

    def test_fail_closed_invalid_evidence(self):
        bad = [dict(ATTEMPT, sha="short"),
               dict(ATTEMPT, status="completed"),
               dict(ATTEMPT, at="2026-11-18T12:00:00"),
               dict(ATTEMPT, at="no-time")]
        for attempt in bad:
            with self.subTest(attempt=attempt), self.assertRaises(ValueError):
                deployment_receipt("ocpp-csms", attempt)
        for name in ("unknown", "gway-002"):
            with self.assertRaises(ValueError):
                deployment_receipt(name, ATTEMPT)
        with self.assertRaises(ValueError):
            self.receipt(observed_sha="invalid")
        with self.assertRaises(ValueError):
            self.receipt(health="green")

    def test_snapshot_distinguishes_missing_ci_pending_and_accepted(self):
        receipt = self.receipt(observed_sha=SHA, health="healthy")
        self.assertEqual(development_snapshot(receipt=receipt)["stage"], "unknown")
        self.assertEqual(development_snapshot(receipt=receipt, github_head=SHA,
                                              ci="failure")["stage"], "blocked")
        self.assertEqual(development_snapshot(receipt=receipt, github_head=OTHER,
                                              ci="success")["stage"], "pending")
        self.assertEqual(development_snapshot(receipt=receipt, github_head=SHA,
                                              ci="success")["stage"], "review")
        self.assertEqual(development_snapshot(receipt=receipt, github_head=SHA,
                                              ci="success", blocked_reason="field gate")["stage"],
                         "blocked")

    def test_rejects_forged_receipts(self):
        receipt = self.receipt(observed_sha=SHA, health="healthy")
        for forged in (dict(receipt, acceptance="verified"),
                       dict(receipt, installed_sha=OTHER),
                       dict(receipt, evidence="verified"),
                       dict(receipt, health="healthy", evidence="incomplete"),
                       {"schema": "gway.deployment-receipt.v1"}):
            with self.subTest(forged=forged), self.assertRaises(ValueError):
                development_snapshot(receipt=forged, github_head=SHA, ci="success")

    def test_snapshot_does_not_promote_attempt_to_live_proof(self):
        receipt = self.receipt()
        result = development_snapshot(receipt=receipt, github_head=SHA, ci="success")
        self.assertEqual(result["stage"], "unknown")
        self.assertIn("installed release", result["reason"])
        with self.assertRaises(ValueError):
            development_snapshot(receipt=receipt, ci="success", github_head="main")


if __name__ == "__main__":
    unittest.main()
