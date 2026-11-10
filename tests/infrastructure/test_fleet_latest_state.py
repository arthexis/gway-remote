"""Offline latest-state semantics; no event history or network."""
import unittest
from datetime import datetime, timedelta, timezone
from gway_remote.fleet_latest_state import LatestFleetState

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)

class LatestFleetTests(unittest.TestCase):
    def test_idempotent_duplicate_and_newer_replaces(self):
        cache = LatestFleetState(ttl_seconds=60)
        self.assertTrue(cache.update("gway-001", {"online": True}, sequence=1,
                                     observed_at=NOW, authenticated=True))
        self.assertFalse(cache.update("gway-001", {"online": True}, sequence=1,
                                      observed_at=NOW, authenticated=True))
        self.assertTrue(cache.update("gway-001", {"online": False}, sequence=2,
                                     observed_at=NOW + timedelta(seconds=1), authenticated=True))
        self.assertFalse(cache.update("gway-001", {"online": True}, sequence=1,
                                      observed_at=NOW, authenticated=True))
        self.assertEqual(cache.snapshot(now=NOW + timedelta(seconds=2))["gway-001"]["status"],
                         {"online": False})

    def test_conflicting_same_sequence_and_untrusted_rejected(self):
        cache = LatestFleetState()
        with self.assertRaises(PermissionError):
            cache.update("gway-001", {}, sequence=1, observed_at=NOW)
        cache.update("gway-001", {"online": True}, sequence=1,
                     observed_at=NOW, authenticated=True)
        with self.assertRaises(ValueError):
            cache.update("gway-001", {"online": False}, sequence=1,
                         observed_at=NOW, authenticated=True)
        with self.assertRaises(ValueError):
            cache.update("gway-001", {}, sequence=2,
                         observed_at=NOW - timedelta(seconds=1), authenticated=True)

    def test_ttl_does_not_show_stale_online(self):
        cache = LatestFleetState(ttl_seconds=60)
        cache.update("gway-001", {"online": True}, sequence=1,
                     observed_at=NOW, authenticated=True)
        self.assertEqual(cache.snapshot(now=NOW + timedelta(seconds=61))["gway-001"]["freshness"],
                         "stale")
        self.assertIsNone(cache.snapshot(now=NOW + timedelta(seconds=61))["gway-001"]["status"])

    def test_no_sequence_or_bad_time_fails_closed(self):
        cache = LatestFleetState()
        with self.assertRaises(ValueError):
            cache.update("gway-001", {}, sequence=None, observed_at=NOW, authenticated=True)
        with self.assertRaises(ValueError):
            cache.update("gway-001", {}, sequence=1, observed_at=NOW.replace(tzinfo=None),
                         authenticated=True)

if __name__ == "__main__":
    unittest.main()
