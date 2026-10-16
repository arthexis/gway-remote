import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote import mobile


class MobileLCDTests(unittest.TestCase):
    def test_catalog_declares_two_bounded_lines(self):
        command = next(x for x in mobile.commands() if x["name"] == "lcd-message")
        self.assertFalse(command["read_only"])
        self.assertEqual(set(command["arguments"]), {"line1", "line2", "duration_seconds"})
        self.assertTrue(all(command["arguments"][name]["max_length"] == 16 for name in ("line1", "line2")))

    def test_valid_event_is_written_and_expires(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(mobile, "LCD_DIR", Path(root)):
                result = mobile.execute("lcd-message", {"line1": "1234567890123456", "line2": "Hello"})
                self.assertTrue(result["queued"])
                lines = (Path(root) / mobile.LCD_EVENT).read_text().splitlines()
                self.assertEqual(lines[:2], ["1234567890123456", "Hello"])
                self.assertEqual(len(lines), 3)

    def test_custom_duration_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(mobile, "LCD_DIR", Path(root)):
                result = mobile.execute("lcd-message", {"line1": "Hello", "line2": "", "duration_seconds": 300})
                self.assertEqual(result["duration_seconds"], 300)
                for value in (0, 31, 301, True, "60"):
                    with self.subTest(value=value), self.assertRaises(ValueError):
                        mobile.execute("lcd-message", {"line1": "Hello", "line2": "", "duration_seconds": value})

    def test_sound_whitelist(self):
        names = next(x for x in mobile.commands() if x["name"] == "sound-play")
        self.assertEqual(names["arguments"]["sound"]["choices"], list(mobile.SOUNDS))
        with patch.object(mobile.subprocess, "run") as run:
            self.assertEqual(mobile.execute("sound-play", {"sound": "notice"}), {"played": "notice"})
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0], ["/usr/local/bin/sound", "notice"])
        with self.assertRaises(ValueError):
            mobile.execute("sound-play", {"sound": "anything; rm -rf /"})

    def test_explicit_motif_preview(self):
        with patch.object(mobile.subprocess, "run") as run:
            self.assertEqual(
                mobile.execute("sound-play", {"sound": "notice", "motif": "github-actions"}),
                {"played": "notice", "motif": "github-actions"},
            )
            self.assertEqual(
                run.call_args.args[0],
                ["/usr/local/bin/sound", "--motif", "github-actions", "notice"],
            )
        for motif in ("", "../other", "--backend", "bad motif", 42):
            with self.subTest(motif=motif), self.assertRaises(ValueError):
                mobile.execute("sound-play", {"sound": "notice", "motif": motif})

    def test_list_installed_motifs(self):
        from subprocess import CompletedProcess
        with patch.object(mobile.subprocess, "run",
                          return_value=CompletedProcess([], 0, '["codex", "github-actions", "wifi"]')) as run:
            self.assertEqual(
                mobile.execute("sound-motifs", {}),
                {"motifs": ["codex", "github-actions", "wifi"]},
            )
            self.assertEqual(run.call_args.args[0], ["/usr/local/bin/sound", "--list-motifs"])
        with self.assertRaises(ValueError):
            mobile.execute("sound-motifs", {"unexpected": True})

    def test_rejects_bad_messages(self):
        for value in [
            {"line1": "x" * 17, "line2": ""},
            {"line1": "x\ny", "line2": ""},
            {"line1": "☃", "line2": ""},
            {"line1": "", "line2": ""},
            {"line1": "only"},
            {"line1": 1, "line2": "ok"},
        ]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    mobile.execute("lcd-message", value)


if __name__ == "__main__":
    unittest.main()
