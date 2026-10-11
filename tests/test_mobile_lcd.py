import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote import mobile


class MobileLCDTests(unittest.TestCase):
    def test_catalog_declares_two_bounded_lines(self):
        command = next(x for x in mobile.commands() if x["name"] == "lcd-message")
        self.assertFalse(command["read_only"])
        self.assertEqual(set(command["arguments"]), {"line1", "line2"})
        self.assertTrue(all(x["max_length"] == 16 for x in command["arguments"].values()))

    def test_valid_event_is_written_and_expires(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(mobile, "LCD_DIR", Path(root)):
                result = mobile.execute("lcd-message", {"line1": "1234567890123456", "line2": "Hello"})
                self.assertTrue(result["queued"])
                lines = (Path(root) / mobile.LCD_EVENT).read_text().splitlines()
                self.assertEqual(lines[:2], ["1234567890123456", "Hello"])
                self.assertEqual(len(lines), 3)

    def test_rejects_bad_messages(self):
        for value in [
            {"line1": "x" * 17, "line2": ""},
            {"line1": "x\\ny", "line2": ""},
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
