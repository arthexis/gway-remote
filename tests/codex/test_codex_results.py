"""Result reconciliation is evidence gathering, not automatic approval."""
import json
import tempfile
import unittest
from pathlib import Path
from gway_remote.codex_results import reconcile


class ReconciliationTests(unittest.TestCase):
    def test_missing_files(self):
        r = reconcile(Path("/nonexistent/final"), None, None, "succeeded")
        self.assertEqual(r["reported_outcome"], "unknown")
        self.assertEqual(r["verification"], "unverified")

    def test_structured_claim_and_unverified_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final = root / "final"
            final.write_text('{"outcome":"completed","notes":"done"}')
            log = root / "log"
            log.write_text("https://github.com/arthexis/gway-remote/pull/68")
            r = reconcile(final, log, root, "succeeded")
            self.assertEqual(r["reported_outcome"], "completed")
            self.assertFalse(json.loads(r["artifacts_json"])[0]["verified"])

    def test_prose_cannot_certify_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "final"
            p.write_text("Everything completed and CI passed!")
            r = reconcile(p, None, None, "succeeded")
            self.assertEqual(r["reported_outcome"], "unknown")
            self.assertEqual(r["verification"], "unverified")

    def test_interrupted_never_claims_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "final"
            p.write_text('{"outcome":"completed"}')
            r = reconcile(p, None, None, "interrupted")
            self.assertEqual(r["reported_outcome"], "not_completed")
