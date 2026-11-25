from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from gway_remote.activity_feed import ActivityFeedStore
from gway_remote import activity_feed_local as local

class LocalWatchtowerFeedTest(TestCase):
    def test_local_ready_and_broker_are_idempotent(self):
        with TemporaryDirectory() as temp:
            store = ActivityFeedStore(Path(temp)/"events.sqlite3")
            local.ready(store)
            local.ready(store)
            local.bind(store)
            try:
                for _ in range(2):
                    self.assertTrue(local.broker("agentops","gway-001","test-attempt","started",
                        "2026-11-24T00:00:00Z",None))
                self.assertFalse(local.broker("unknown","gway-001","x","started",
                        "2026-11-24T00:00:00Z",None))
                self.assertEqual(len(store.list_recent()["items"]),2)
            finally:
                local.bind(None)

    def test_inventory_baseline_and_transition(self):
        with TemporaryDirectory() as temp:
            store = ActivityFeedStore(Path(temp)/"events.sqlite3")
            def snap(at, reach):
                return {"generated_at":at,"nodes":[{"node":"gway-001","reachable":reach,"identity_verified":True}]}
            first = snap("2026-11-24T00:00:00Z","reachable")
            second = snap("2026-11-24T00:01:00Z","unknown")
            self.assertEqual(local.inventory(store,loader=lambda:first),0)
            self.assertEqual(local.inventory(store,loader=lambda:second),1)
            self.assertEqual(local.inventory(store,loader=lambda:second),0)
            self.assertEqual(store.list_recent()["items"][0]["event"]["type"],"fleet.contact_unknown")
