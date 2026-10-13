"""Authoritative mobile command admission and catalog contract."""
import unittest
from gway_remote import mobile

# This is deliberately independent of the implementation's OPERATIONS mapping.
# Review every addition to this list as an API exposure/security change.
EXPECTED_COMMANDS = frozenset({
    "status", "status-quick", "probe-csms", "lcd-message", "sound-play",
    "simulator-discover", "simulator-start", "simulator-stop",
    "simulator-status", "simulator-results", "csms-view", "benchmark-echo",
    "codex-tasks", "codex-task", "codex-issues",
})
READ_ONLY = frozenset({
    "status", "status-quick", "probe-csms", "simulator-discover",
    "simulator-status", "simulator-results", "csms-view", "benchmark-echo",
    "codex-tasks", "codex-task", "codex-issues",
})


class MobileCommandContractTests(unittest.TestCase):
    def test_exact_allowlist_and_metadata(self):
        commands = mobile.commands()
        names = [item["name"] for item in commands]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), EXPECTED_COMMANDS)
        self.assertEqual({item["name"] for item in commands if item["read_only"]}, READ_ONLY)
        self.assertTrue(all(isinstance(item["arguments"], dict) for item in commands))

    def test_rejects_unapproved_commands(self):
        for name in ("run", "deploy-batch", "logs", "reconcile", "report-bundle"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                mobile.execute(name, {})
