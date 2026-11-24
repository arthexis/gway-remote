"""Hermetic Stage 2 outbox and CLI tests."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from gway_remote.activity_feed import EventConflict, FeedCapacityError, validate_event
from gway_remote.activity_feed_outbox import Outbox, publish_best_effort, MAX_AGE
from gway_remote.activity_feed_cli import main, HTTPSPublisher
from tests.core.test_activity_feed import event


class OutboxTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.now = 1000
        self.box = Outbox(self.root / "queue", clock=lambda: self.now, capacity=2)

    def test_replay_and_capacity(self):
        self.assertTrue(publish_best_effort(self.box, event()))
        self.assertEqual(self.box.enqueue(event()), "pending")
        changed = event()
        changed["data"]["title"] = "changed"
        with self.assertRaises(EventConflict):
            self.box.enqueue(changed)
        self.box.enqueue(event("two"))
        with self.assertRaises(FeedCapacityError):
            self.box.enqueue(event("three"))
        self.assertFalse(publish_best_effort(self.box, event("three")))

    def test_restart_retry_then_ack(self):
        self.box.enqueue(event())
        seen = []
        def fail(value):
            seen.append(value)
            return "retry"
        self.assertEqual(self.box.flush(fail)["retry"], 1)
        self.assertEqual(self.box.flush(fail)["attempted"], 0)
        self.now += 5
        self.box = Outbox(self.root / "queue", clock=lambda: self.now)
        self.assertEqual(self.box.flush(lambda value: seen.append(value) or "delivered")["delivered"], 1)
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(self.box.enqueue(event()), "delivered")

    def test_expired_and_dead_are_not_replayed(self):
        self.box.enqueue(event())
        self.now += MAX_AGE
        self.assertEqual(self.box.flush(lambda _: self.fail("expired event sent"))["attempted"], 0)
        self.assertEqual(self.box.status()["dead"], 1)
        self.assertEqual(self.box.purge_dead(), 1)

    def test_cli_enqueue_never_uses_network(self):
        config = self.root / "feed.json"
        config.write_text(json.dumps({"endpoint": "https://example.test/api/feed/events",
                                       "source": "/gway/deploy", "node": "gway-001",
                                       "token_file": str(self.root / "not-created")}))
        config.chmod(0o600)
        output = StringIO()
        with redirect_stdout(output), patch("gway_remote.activity_feed_cli.HTTPSPublisher",
                                            side_effect=AssertionError("network attempted")):
            self.assertEqual(main(["Backup completed"], config_path=config, state_path=self.root / "queue"), 0)
        self.assertEqual(json.loads(output.getvalue())["state"], "pending")
        self.assertEqual(self.box.status()["pending"], 1)

    def test_transport_requires_exact_receipt(self):
        token = self.root / "token"
        token.write_text("gwr_" + "a" * 24 + "_example")
        token.chmod(0o600)
        value = validate_event(event())
        from unittest.mock import MagicMock
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.status = 201
        response.read.return_value = json.dumps({"seq": 1, "received_at": value["time"], "event": value}).encode()
        publisher = HTTPSPublisher({"endpoint": "https://example.test/api/feed/events",
                                    "source": value["source"], "token_file": str(token)}, opener=opener)
        self.assertEqual(publisher(value), "delivered")
        response.read.return_value = b'{"seq":1}'
        self.assertEqual(publisher(value), "retry")
