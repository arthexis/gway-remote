import tempfile
import unittest
from pathlib import Path

from gway_remote.attempts import mark, read_attempts
from gway_remote.logs import capture_log, log_filename, read_log, sanitize, list_logs
from gway_remote.report_bundle import bundle


class LogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_capture_and_read(self):
        name = log_filename("ocpp-csms", "a" * 40)
        with capture_log(self.root, name):
            import os
            os.write(1, b"installation output\n")
            os.write(2, b"warning\n")
        text = read_log(self.root, "ocpp-csms", lines=2)
        self.assertIn("installation output", text)
        self.assertIn("warning", text)
        self.assertEqual(list_logs(self.root, "ocpp-csms")[0].name, name)

    def test_sanitize(self):
        value = "Authorization: Bearer abc123 token=secret https://user:pass@host/path"
        clean = sanitize(value)
        self.assertNotIn("abc123", clean)
        self.assertNotIn("secret", clean)
        self.assertNotIn("user:pass", clean)

    def test_export_bundle(self):
        name = log_filename("ocpp-csms", "a" * 40)
        with capture_log(self.root, name):
            import os
            os.write(1, b"token=supersecret\n")
        mark("ocpp-csms", "a" * 40, "failed", self.root, log=name, error="token=private")
        output = self.root / "artifact"
        summary = bundle(output, self.root, probe=lambda _: None)
        self.assertIn("ocpp-csms", summary)
        self.assertTrue((output / "status.json").is_file())
        exported = (output / "logs" / name).read_text()
        self.assertNotIn("supersecret", exported)
        self.assertNotIn("private", (output / "status.json").read_text())
        self.assertIn("[REDACTED]", exported)

    def test_invalid_component(self):
        with self.assertRaises(ValueError):
            log_filename("../other", "a" * 40)
        with self.assertRaises(ValueError):
            read_log(self.root, lines=0)


if __name__ == "__main__":
    unittest.main()
