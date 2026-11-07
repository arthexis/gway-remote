"""Regression tests for journals containing retired or newly added targets."""
import json
import tempfile
import unittest
from pathlib import Path

from gway_remote.attempts import attempted_shas, mark, read_attempts


class LegacyAttemptJournalTests(unittest.TestCase):
    def test_legacy_entry_is_preserved_but_not_active(self):
        with tempfile.TemporaryDirectory() as directory:
            sha = "a" * 40
            legacy = {"ocpp-simulator": {"sha": sha, "status": "installed", "at": "2026-01-01T00:00:00+00:00"}}
            path = Path(directory) / "attempts.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")
            self.assertEqual(read_attempts(directory), legacy)
            self.assertNotIn("ocpp-simulator", attempted_shas(directory))
            mark("ocpp-csms", "b" * 40, "installed", directory)
            result = read_attempts(directory)
            self.assertEqual(result["ocpp-simulator"], legacy["ocpp-simulator"])
            self.assertEqual(attempted_shas(directory)["ocpp-csms"], "b" * 40)

    def test_malformed_legacy_record_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "attempts.json").write_text(
                json.dumps({"ocpp-simulator": {"status": "installed"}}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "invalid attempt journal"):
                read_attempts(directory)


if __name__ == "__main__":
    unittest.main()
