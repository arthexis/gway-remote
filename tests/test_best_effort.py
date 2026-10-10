import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gway_remote.attempts import read_attempts
from gway_remote.best_effort import appliance_lock, execute
from gway_remote.reconcile import TARGETS

NOW = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
SHA = "a" * 40


class GitHub:
    def __init__(self):
        self.heads = {repo: SHA for _, repo in TARGETS}

    def get(self, path):
        for repo, sha in self.heads.items():
            if path == f"repos/{repo}/branches/main":
                return {"commit": {"sha": sha}}
            if path.startswith(f"repos/{repo}/actions/runs?"):
                return {"workflow_runs": [{
                    "head_sha": sha,
                    "created_at": (NOW - timedelta(minutes=21)).isoformat(),
                    "status": "completed", "conclusion": "success"}]}
        raise AssertionError(path)


class BestEffortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.client = GitHub()
        self.calls = []

    def installers(self, failing=()):
        def make(name):
            def deploy(sha):
                self.calls.append(name)
                if name in failing:
                    raise RuntimeError("simulated failure")
            return deploy
        return {name: make(name) for name, _ in TARGETS}

    def test_ordered_once_and_durable(self):
        result = execute(self.client, NOW, self.installers(), self.path)
        self.assertEqual(result["decision"], "completed")
        self.assertEqual(self.calls, [name for name, _ in TARGETS])
        self.assertEqual(execute(self.client, NOW, self.installers(), self.path)["decision"], "idle")
        self.assertEqual(len(self.calls), 3)

    def test_failure_does_not_block_next_or_retry(self):
        execute(self.client, NOW, self.installers(("ocpp-simulator",)), self.path)
        self.assertEqual(self.calls, [name for name, _ in TARGETS])
        self.assertEqual(read_attempts(self.path)["ocpp-simulator"]["status"], "failed")
        execute(self.client, NOW, self.installers(), self.path)
        self.assertEqual(len(self.calls), 3)

    def test_crash_before_installer_is_not_retried(self):
        from gway_remote.attempts import mark
        mark("ocpp-csms", SHA, "started", self.path)
        execute(self.client, NOW, self.installers(), self.path)
        self.assertNotIn("ocpp-csms", self.calls)

    def test_shared_lock_blocks_concurrent_batch(self):
        with appliance_lock(self.path / "appliance.lock"):
            with self.assertRaisesRegex(RuntimeError, "already active"):
                execute(self.client, NOW, self.installers(), self.path)

    def test_new_revision_is_eligible(self):
        execute(self.client, NOW, self.installers(), self.path)
        repo = TARGETS[0][1]
        self.client.heads[repo] = "b" * 40
        execute(self.client, NOW, self.installers(), self.path)
        self.assertEqual(self.calls[-1], "ocpp-csms")
        self.assertEqual(len(self.calls), 4)


if __name__ == "__main__":
    unittest.main()
