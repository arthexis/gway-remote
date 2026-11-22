"""Hermetic LCD/Sound receiver regression suite (unittest-discoverable)."""
from datetime import datetime, timedelta, timezone
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from gway_remote import lcd_sound_event as m


def make_event(action="play", arguments=None, device="sound", **changes):
    event = {"schema": 1, "node": "gway-001", "origin": "watchtower",
             "request_id": "ab" * 16,
             "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat(),
             "device": device, "action": action,
             "arguments": arguments if arguments is not None else {"name": "notice"},
             "hops": 0}
    event.update(changes)
    return event


class LcdSoundReceiverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        parent = Path(self.temp.name) / "private"
        parent.mkdir(mode=0o700)
        parent.chmod(0o700)
        self.journal = parent / "events.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def test_sound_exactly_once_and_private_journal(self):
        calls = []
        def runner(argv, **kw):
            calls.append((argv, kw))
            return SimpleNamespace(returncode=0)
        event = make_event()
        self.assertEqual(m.receive(event, trusted_node="gway-001",
                                   db_path=self.journal, run=runner),
                         {"status": "succeeded", "duplicate": False})
        self.assertEqual(m.receive(event, trusted_node="gway-001",
                                   db_path=self.journal, run=runner),
                         {"status": "succeeded", "duplicate": True})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ["gway-lcd-sound", "sound", "play", "notice"])
        self.assertEqual(calls[0][1]["env"]["GWAY_LCD_SOUND_FORCE_LOCAL"], "1")
        self.assertEqual(self.journal.stat().st_mode & 0o777, 0o600)

    def test_rebinding_id_denied(self):
        runner = lambda *a, **kw: SimpleNamespace(returncode=0)
        m.receive(make_event(), trusted_node="gway-001", db_path=self.journal, run=runner)
        with self.assertRaises(PermissionError):
            m.receive(make_event(arguments={"name": "error"}), trusted_node="gway-001",
                      db_path=self.journal, run=runner)

    def test_ambiguous_execution_not_replayed(self):
        calls = []
        def failing(*a, **kw):
            calls.append(1)
            raise OSError("offline")
        event = make_event()
        first = m.receive(event, trusted_node="gway-001", db_path=self.journal, run=failing)
        second = m.receive(event, trusted_node="gway-001", db_path=self.journal, run=failing)
        self.assertEqual(first["status"], "uncertain")
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(calls), 1)

    def test_identity_and_hop_guards(self):
        for modification in ({"node": "gway-002"}, {"hops": 1}, {"origin": "gway-001"}):
            with self.subTest(modification=modification), self.assertRaises(PermissionError):
                m.validate(make_event(**modification), trusted_node="gway-001")

    def test_untrusted_inputs(self):
        modifications = (
            {"expires_at": "1999-01-01T00:00:00+00:00"},
            {"expires_at": "2100-01-01T00:00:00+00:00"},
            {"request_id": "not-a-uuid"}, {"hops": False},
            {"device": "exec"}, {"action": "shell"},
            {"origin": "../outside"},
            {"arguments": {"name": "warning; sh -c id"}},
            {"arguments": {"name": "notice", "extra": "bad"}},
        )
        for change in modifications:
            with self.subTest(change=change), self.assertRaises((ValueError, PermissionError)):
                m.validate(make_event(**change), trusted_node="gway-001")

    def test_lcd_overlay_is_delegated_to_local_owner(self):
        calls = []
        def runner(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=0)
        event = make_event(device="lcd", action="show",
                           arguments={"line1": "Watchtower", "line2": "Ready", "seconds": 20})
        result = m.receive(event, trusted_node="gway-001", db_path=self.journal, run=runner)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(calls, [["gway-lcd-sound", "lcd", "show",
                                  "Watchtower", "Ready", "--seconds", "20"]])

    def test_sound_event_retains_mapping_and_cooldown(self):
        event = make_event(action="event", arguments={
            "event": "deploy-verified", "source": "gway-remote", "within": 30})
        m.validate(event, trusted_node="gway-001")
        self.assertEqual(m.argv_for(event), ["sound", "--event", "deploy-verified",
                                            "--source", "gway-remote", "--within", "30"])

    def test_sequence_validation(self):
        good = json.dumps({"format": "gway-piano-v1", "notes": [[440, 0.1, 0.0]]})
        m.validate(make_event(action="sequence", arguments={"sequence": good}),
                   trusted_node="gway-001")
        bad = '{"format":"gway-piano-v1","notes":[[5000,1,0]]}'
        with self.assertRaises(ValueError):
            m.validate(make_event(action="sequence", arguments={"sequence": bad}),
                       trusted_node="gway-001")

    def test_world_readable_journal_rejected(self):
        self.journal.write_bytes(b"")
        self.journal.chmod(0o644)
        with self.assertRaises(PermissionError):
            m.receive(make_event(), trusted_node="gway-001", db_path=self.journal)
