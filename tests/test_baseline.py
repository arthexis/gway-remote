"""Baseline never triggers a deploy, session or service transition."""
import unittest
from unittest.mock import patch

from gway_remote.baseline import baseline


class BaselineTests(unittest.TestCase):
    def test_no_mutating_commands(self):
        calls = []
        def fake(argv, timeout=8):
            calls.append(argv)
            return {"ok": False, "value": None}
        with patch("gway_remote.baseline.command", side_effect=fake):
            result = baseline()
        self.assertEqual(result["active_transactions"], "not-measured")
        self.assertTrue(all(x[2] == "is-active" for x in calls))
        self.assertFalse(any("start" in x or "restart" in x for x in calls))


if __name__ == "__main__":
    unittest.main()
