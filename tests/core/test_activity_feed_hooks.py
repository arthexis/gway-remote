"""Hermetic feed producer contract tests."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from gway_remote.activity_feed_hooks import deployment, observe_inventory, inventory_once, publish
from gway_remote.activity_feed_outbox import Outbox

STAMP = "2026-11-24T10:00:00Z"


class ProducerTests(unittest.TestCase):
    def test_deploy_identity_and_rollback(self):
        args = dict(repository="arthexis/gway-remote", node="gway-001", attempt="one", at=STAMP, sha="a"*40)
        first = deployment("/gway/test", state="activated", **args)
        self.assertEqual(first, deployment("/gway/test", state="activated", **args))
        self.assertEqual(first["data"]["severity"], "info")
        rollback = deployment("/gway/test", state="rollback_verified", **args)
        self.assertNotEqual(first["id"], rollback["id"])
        self.assertNotIn("commit", rollback["data"])
        self.assertEqual(first["data"]["correlation_id"], rollback["data"]["correlation_id"])

    def test_disabled_and_unavailable_sink(self):
        with patch("gway_remote.activity_feed_hooks.enabled", return_value=False):
            self.assertFalse(publish(lambda _: self.fail("unexpected build")))
        with patch("gway_remote.activity_feed_hooks.enabled", side_effect=OSError):
            self.assertFalse(publish(lambda _: None))

    def test_inventory_baseline_and_transition(self):
        def snapshot(at, reach):
            return {"generated_at": at, "nodes": [{"node":"gway-001","reachable":reach,"identity_verified":True}]}
        with TemporaryDirectory() as tmp:
            box = Outbox(Path(tmp)/"queue", binding="test")
            config = {"source":"/gway/test"}
            self.assertEqual(inventory_once(box, config, loader=lambda: snapshot(STAMP,"reachable")), 0)
            new = snapshot("2026-11-24T10:05:00Z","unknown")
            self.assertEqual(inventory_once(box, config, loader=lambda: new), 1)
            self.assertEqual(inventory_once(box, config, loader=lambda: new), 0)
            seen = []
            box.flush(lambda e: seen.append(e) or "delivered")
            self.assertEqual([e["type"] for e in seen], ["fleet.contact_unknown"])
            self.assertEqual(seen[0]["data"]["severity"], "warning")
