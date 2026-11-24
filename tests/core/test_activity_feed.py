"""Hermetic Stage 1A activity feed tests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gway_remote.activity_feed import ActivityFeedStore, EventConflict, FeedCapacityError, validate_event


def event(event_id="one", time="2026-11-24T10:00:00-06:00"):
    return {"specversion": "1.0", "id": event_id, "source": "/gway/deploy",
            "type": "deployment.completed", "time": time,
            "data": {"title": "Deploy completed", "summary": "Example", "category": "deployment",
                     "severity": "success", "node": "gway-001"}}


class ActivityFeedTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "feed.sqlite3"
        self.now = datetime(2026, 11, 24, 16, tzinfo=timezone.utc)
        self.store = ActivityFeedStore(self.path, clock=lambda: self.now, max_rows=3)

    def append(self, value):
        return self.store.append(value, producer="node-001", allowed_source="/gway/deploy")

    def test_replay_and_conflict_persist(self):
        first, inserted = self.append(event())
        self.assertTrue(inserted)
        self.store = ActivityFeedStore(self.path)
        replay, inserted = self.append(event(time="2026-11-24T16:00:00Z"))
        self.assertFalse(inserted)
        self.assertEqual(first, replay)
        changed = event()
        changed["data"]["title"] = "Changed"
        with self.assertRaises(EventConflict):
            self.append(changed)
        self.assertEqual(self.store.list_after()["items"], [first])

    def test_source_spoof_rejected_without_write(self):
        value = event()
        value["source"] = "/gway/other"
        with self.assertRaises(PermissionError):
            self.append(value)
        self.assertEqual(self.store.list_after()["items"], [])

    def test_validation_rejects_invalid_and_oversized_values(self):
        for key, value in [("time", "2026-11-24"), ("id", ""), ("specversion", "2.0")]:
            with self.subTest(key=key):
                malformed = event()
                malformed[key] = value
                with self.assertRaises(ValueError):
                    self.append(malformed)
        for key, value in [("title", "x" * 161), ("summary", "x" * 1025),
                           ("url", "javascript:alert(1)"), ("url", "https://user:pass@example.com"),
                           ("issue", True), ("unknown", "secret"), ("severity", [])]:
            with self.subTest(key=key, value=str(value)[:40]):
                malformed = event()
                malformed["data"][key] = value
                with self.assertRaises(ValueError):
                    self.append(malformed)
        self.assertEqual(self.store.list_after()["items"], [])

    def test_incremental_cursor_handles_late_arrivals(self):
        first, _ = self.append(event())
        second, _ = self.append(event("late", "2026-10-01T00:00:00Z"))
        page = self.store.list_after(limit=1)
        self.assertTrue(page["has_more"])
        self.assertEqual(page["items"], [first])
        next_page = self.store.list_after(page["next_cursor"], limit=1)
        self.assertEqual(next_page["items"], [second])
        self.assertFalse(next_page["has_more"])
        self.assertEqual(self.store.list_after(category="other")["items"], [])
        for cursor, limit in [(-1, 1), (0, 101), (True, 1)]:
            with self.assertRaises(ValueError):
                self.store.list_after(cursor, limit=limit)

    def test_concurrent_duplicate_only_inserted_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.append(event()), range(12)))
        self.assertEqual(sum(inserted for _, inserted in results), 1)
        self.assertEqual(len(self.store.list_after()["items"]), 1)

    def test_capacity_prune_and_monotonic_cursor(self):
        for event_id in ("a", "b", "c"):
            last, _ = self.append(event(event_id))
        with self.assertRaises(FeedCapacityError):
            self.append(event("d"))
        self.assertFalse(self.append(event("a"))[1])
        self.now += timedelta(days=181)
        self.assertEqual(self.store.prune(limit=2), 2)
        replay, inserted = self.append(event("a"))
        self.assertTrue(inserted)
        self.assertGreater(replay["seq"], last["seq"])
        self.assertEqual(self.store.list_after(last["seq"])["items"], [replay])

    def test_normalization_does_not_mutate_input(self):
        value = event()
        normalized = validate_event(value)
        self.assertEqual(normalized["time"], "2026-11-24T16:00:00.000000Z")
        self.assertEqual(value["time"], "2026-11-24T10:00:00-06:00")

    def test_rfc3339_fraction_offset_and_source(self):
        self.assertEqual(validate_event(event(time="2026-11-24T16:00:00.1Z"))["time"],
                         "2026-11-24T16:00:00.100000Z")
        with self.assertRaises(ValueError):
            validate_event(event(time="2026-11-24T16:00:00+01:60"))
        malformed = event()
        malformed["source"] = "not a URI"
        with self.assertRaises(ValueError):
            validate_event(malformed)

    def test_recent_pages_and_get(self):
        first, _ = self.append(event("first"))
        second, _ = self.append(event("second"))
        page = self.store.list_recent(limit=1)
        self.assertEqual(page["items"], [second])
        self.assertTrue(page["has_more"])
        self.assertEqual(self.store.list_recent(before=page["next_cursor"])["items"], [first])
        self.assertEqual(self.store.get(first["seq"]), first)
        self.assertIsNone(self.store.get(99))
