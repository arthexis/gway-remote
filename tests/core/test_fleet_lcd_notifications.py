"""Unittest-compatible hermetic fleet target and debounce behavior."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from gway_remote import fleet_lcd_notifications as fleet

NOW = datetime(2026, 11, 24, 7, 0, tzinfo=timezone.utc)


class FleetNotificationTests(unittest.TestCase):
    def test_fixed_pinned_ssh_target_and_safe_allowlist(self):
        seen = []
        def run(args, **kwargs):
            seen.append(args)
            return SimpleNamespace(returncode=0)
        self.assertEqual(fleet.probe("ocpp-abb-1", "ocpp-reports-ingest.service",
                                     run=run), "healthy")
        self.assertEqual(seen[0][0], "ssh")
        self.assertIn("StrictHostKeyChecking=yes", seen[0])
        self.assertEqual(seen[0][-4:],
                         ["ubuntu@ocpp-abb-1", "/usr/bin/systemctl", "is-active",
                          "--quiet", "ocpp-reports-ingest.service"][-4:])
        with self.assertRaises(ValueError):
            fleet.probe("unknown-node", "sshd.service", run=run)
        with self.assertRaises(ValueError):
            fleet.probe("ocpp-abb-1", "bash -c evil", run=run)

    def test_ssh_and_service_failures_are_distinct(self):
        for code, state in ((0, "healthy"), (3, "down"), (255, "unreachable"),
                            (4, "degraded")):
            with self.subTest(code=code):
                found = fleet.probe("gelectriic.com", "nginx.service",
                                    run=lambda *a, **kw: SimpleNamespace(returncode=code))
                self.assertEqual(found, state)

    def test_two_failures_and_two_recoveries_same_episode(self):
        current, event = fleet.update(None, "healthy", NOW)
        self.assertIsNone(event)
        current, event = fleet.update(current, "down", NOW)
        self.assertIsNone(event)
        current, event = fleet.update(current, "down", NOW + timedelta(minutes=1))
        self.assertEqual(event, "down")
        self.assertEqual(current["active"], "down")
        identity = current["episode"]
        current, event = fleet.update(current, "down", NOW + timedelta(minutes=2))
        self.assertIsNone(event)
        self.assertEqual(current["episode"], identity)
        current, event = fleet.update(current, "healthy", NOW + timedelta(minutes=3))
        self.assertIsNone(event)
        current, event = fleet.update(current, "healthy", NOW + timedelta(minutes=4))
        self.assertEqual(event, "recovered")
        self.assertIsNone(current["active"])
        self.assertEqual(current["episode"], identity)

    def test_unreachable_does_not_claim_service_down(self):
        first, _ = fleet.update(None, "unreachable", NOW)
        second, event = fleet.update(first, "unreachable", NOW + timedelta(minutes=1))
        self.assertEqual(event, "unreachable")
        doc = fleet.event_document("ocpp-abb-1", "ocpp-reports-ingest.service",
                                   event, second["episode"])
        self.assertEqual(doc["target_node"], "ocpp-abb-1")
        self.assertEqual(doc["origin_node"], "gway-001")
        self.assertEqual(doc["state"], "unreachable")
        self.assertEqual(doc["reason_code"], "NODE_UNREACHABLE")
        self.assertEqual(doc["severity"], "error")

    def test_end_to_end_cycle_has_no_rotation_audio(self):
        with tempfile.TemporaryDirectory() as d, patch.object(
                fleet.socket, "gethostname", return_value="gway-001"):
            path = Path(d) / "fleet.json"
            statuses = {("ocpp-abb-1", "ocpp-reports-ingest.service"): "down"}
            observed = []
            def monitor(node, service):
                return statuses.get((node, service), "healthy")
            def sender(document, *, sound):
                observed.append((document, sound))
            fleet.cycle(state=path, now=NOW, monitor=monitor, sender=sender)
            self.assertEqual(observed, [])
            fleet.cycle(state=path, now=NOW + timedelta(minutes=1),
                        monitor=monitor, sender=sender)
            self.assertEqual(len(observed), 1)
            self.assertEqual(observed[-1][1], "critical")
            fleet.cycle(state=path, now=NOW + timedelta(minutes=2),
                        monitor=monitor, sender=sender)
            self.assertEqual(len(observed), 2)
            self.assertIsNone(observed[-1][1])
            statuses.clear()
            fleet.cycle(state=path, now=NOW + timedelta(minutes=3),
                        monitor=monitor, sender=sender)
            fleet.cycle(state=path, now=NOW + timedelta(minutes=4),
                        monitor=monitor, sender=sender)
            self.assertEqual(observed[-1][0]["state"], "recovered")
            self.assertEqual(observed[-1][1], "ok")
            self.assertEqual(path.stat().st_mode & 0o077, 0)

    def test_refuses_other_host(self):
        with tempfile.TemporaryDirectory() as d, patch.object(
                fleet.socket, "gethostname", return_value="laptop"):
            with self.assertRaises(PermissionError):
                fleet.cycle(state=Path(d) / "state", monitor=lambda *args: "healthy")


if __name__ == "__main__":
    unittest.main()
