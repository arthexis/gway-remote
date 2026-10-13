"""Manual appliance batches bypass cooldown but retain deployment safety gates."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from pathlib import Path
import tempfile

from gway_remote.attempt_policy import Candidate, QUIET_PERIOD, plan
from gway_remote.reconcile import TARGETS
from gway_remote.best_effort import execute
from gway_remote.attempts import mark


class ManualBatchQuietTests(unittest.TestCase):
    def candidates(self, now, attempted=False, ci="success"):
        return tuple(
            Candidate(name=name, sha=f"{i + 1:040x}", merged_at=now - timedelta(minutes=1),
                      ci=ci, attempted_sha=f"{i + 1:040x}" if attempted else None)
            for i, (name, _) in enumerate(TARGETS)
        )

    def test_quiet_period_is_preserved_by_default(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(plan(self.candidates(now), now).state, "waiting")
        self.assertEqual(plan(self.candidates(now), now, bypass_quiet=True).state, "ready")

    def test_force_still_requires_green_ci_and_unattempted_revision(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(plan(self.candidates(now, ci="failure"), now, bypass_quiet=True).state, "blocked")
        self.assertEqual(plan(self.candidates(now, attempted=True), now, bypass_quiet=True).state, "idle")

    def test_manual_batch_reaches_installers_before_quiet_period_expires(self):
        now = datetime.now(timezone.utc)
        items = self.candidates(now)
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            with patch("gway_remote.best_effort.collect", return_value=items), \
                 patch("gway_remote.best_effort.main_head", side_effect=lambda _, repo: next(
                     item.sha for item, (name, url) in zip(items, TARGETS) if url == repo)):
                out = execute(object(), now, {name: lambda sha, name=name: calls.append((name, sha))
                                              for name, _ in TARGETS}, directory=tmp, bypass_quiet=True)
        self.assertEqual(out["decision"], "completed")
        self.assertEqual(len(calls), len(TARGETS))
        self.assertTrue(all(x["status"] == "installed" for x in out["results"]))



    def test_failed_revision_retry_is_explicit_and_only_failed(self):
        now = datetime.now(timezone.utc)
        items = self.candidates(now)
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            for i, (name, _) in enumerate(TARGETS):
                mark(name, items[i].sha, "failed" if i == 0 else "installed", tmp)
            with patch("gway_remote.best_effort.collect", side_effect=lambda client, attempts: tuple(
                Candidate(name=x.name, sha=x.sha, merged_at=x.merged_at, ci=x.ci,
                          attempted_sha=attempts.get(x.name)) for x in items)), \
                 patch("gway_remote.best_effort.main_head", side_effect=lambda _, repo: next(
                     item.sha for item, (name, url) in zip(items, TARGETS) if url == repo)):
                runners = {name: lambda sha, name=name: calls.append(name) for name, _ in TARGETS}
                out = execute(object(), now, runners, directory=tmp, bypass_quiet=True)
                self.assertEqual(out["decision"], "idle")
                result = execute(object(), now, runners, directory=tmp,
                                 bypass_quiet=True, retry_failed=True)
                self.assertEqual(result["decision"], "completed")
                self.assertEqual(calls, [items[0].name])

    def test_retry_flag_requires_manual_mode(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "requires explicit manual"):
                execute(object(), now, {}, directory=tmp, retry_failed=True)

if __name__ == "__main__":
    unittest.main()
