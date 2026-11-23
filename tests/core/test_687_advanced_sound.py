"""Receiver validation and at-most-once advanced public options (#687)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import os
import unittest
from unittest.mock import patch

from gway_remote import lcd_sound_event as receiver


def envelope(action, arguments):
    return {"schema": 1, "node": "gway-001", "origin": "watchtower",
            "request_id": "7c" * 16,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat(),
            "device": "sound", "action": action, "arguments": arguments, "hops": 0}


class AdvancedSoundReceiverTests(unittest.TestCase):
    def test_play_advanced_options_build_fixed_argv(self):
        event = envelope("play", {"name": "notice", "volume": 0.45,
                         "repeat": 3, "pause": 0.2, "backend": "gpio",
                         "pin": 18, "within": 5, "dry_run": True})
        receiver.validate(event, trusted_node="gway-001")
        self.assertEqual(receiver.argv_for(event), [
            "gway-lcd-sound", "sound", "play", "notice", "--volume", "0.45",
            "--repeat", "3", "--pause", "0.2", "--backend", "gpio",
            "--pin", "18", "--within", "5", "--dry-run"])

    def test_event_advanced_safe_resolve(self):
        event = envelope("event", {"event": "deploy-verified", "source": "gway-remote",
                         "within": 30.0, "resolve": True})
        receiver.validate(event, trusted_node="gway-001")
        self.assertEqual(receiver.argv_for(event), [
            "sound", "--event", "deploy-verified", "--source", "gway-remote",
            "--within", "30.0", "--resolve"])

    def test_sequence_with_audio_preview(self):
        seq = json.dumps({"format": "gway-piano-v1", "notes": [[440, 0.1, 0.0]]})
        event = envelope("sequence", {"sequence": seq, "volume": 0.4,
                         "backend": "audio", "device": "default", "dry_run": True})
        receiver.validate(event, trusted_node="gway-001")
        self.assertEqual(receiver.argv_for(event), [
            "gway-lcd-sound", "sound", "play", "--sequence", seq,
            "--volume", "0.4", "--backend", "audio", "--device", "default",
            "--dry-run"])

    def test_unsafe_flags_are_rejected_pre_claim(self):
        base = {"name": "notice"}
        bad = [
            {"pin": 19}, {"volume": float("nan")}, {"volume": 1.5},
            {"repeat": True}, {"repeat": 21}, {"repeat": 20, "pause": 3},
            {"backend": "exec"}, {"backend": "gpio", "device": "default"},
            {"backend": "audio", "device": "hw:99"},
            {"motif": "../secret"}, {"unknown": "ignored"},
            {"repeat": 2, "motif": "test"},
        ]
        with TemporaryDirectory() as tmp:
            journal = Path(tmp) / "events.sqlite3"
            for option in bad:
                with self.subTest(option=option):
                    event = envelope("play", dict(base, **option))
                    with self.assertRaises((ValueError, PermissionError)):
                        receiver.receive(event, trusted_node="gway-001",
                                         db_path=journal,
                                         run=lambda *a, **k: self.fail("never execute"))
                    self.assertFalse(journal.exists())

    def test_unknown_event_option_and_illegal_combinations(self):
        for action, args in (
            ("event", {"event": "x", "source": "y", "motif": "codex"}),
            ("event", {"event": "x", "source": "y", "repeat": 2}),
            ("sequence", {"sequence": "{}", "repeat": 3}),
            ("play", {"name": "notice", "resolve": True}),
        ):
            with self.subTest(action=action):
                with self.assertRaises((ValueError, PermissionError)):
                    receiver.validate(envelope(action, args), trusted_node="gway-001")

    def test_dry_run_output_is_captured_and_deduplicated(self):
        with TemporaryDirectory() as tmp:
            private = Path(tmp) / "private"
            private.mkdir(mode=0o700)
            events = private / "events.db"
            calls = []
            def run(argv, **kwargs):
                calls.append(argv)
                return SimpleNamespace(returncode=0, stdout=b"preview\\n")
            event = envelope("play", {"name": "notice", "dry_run": True})
            a = receiver.receive(event, trusted_node="gway-001",
                                 db_path=events, run=run)
            b = receiver.receive(event, trusted_node="gway-001",
                                 db_path=events, run=run)
            self.assertEqual(a["output"], "preview\\n")
            self.assertEqual(b["output"], "preview\\n")
            self.assertTrue(b["duplicate"])
            self.assertEqual(len(calls), 1)

    def test_uncertain_physical_repeat_is_never_replayed(self):
        with TemporaryDirectory() as tmp:
            private = Path(tmp) / "private"
            private.mkdir(mode=0o700)
            journal = private / "events.sqlite3"
            calls = []
            def timeout(argv, **kwargs):
                calls.append(argv)
                raise OSError("uncertain hardware")
            event = envelope("play", {"name": "notice", "repeat": 3, "pause": 0.1})
            a = receiver.receive(event, trusted_node="gway-001",
                                 db_path=journal, run=timeout)
            b = receiver.receive(event, trusted_node="gway-001",
                                 db_path=journal, run=timeout)
            self.assertEqual(a["status"], "uncertain")
            self.assertTrue(b["duplicate"])
            self.assertEqual(len(calls), 1)
