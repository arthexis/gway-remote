"""Issue-first assignment reporting tests (all GitHub operations mocked)."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from gway_remote.codex_reporting import ReportOutbox, assignment_prompt, diagnostic_body


class Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def read(self):
        return json.dumps(self.payload).encode()


class ReportingTests(unittest.TestCase):
    def test_prompt_requires_issue_comment_but_never_closure(self):
        prompt = assignment_prompt("arthexis/gway-remote", 41, "Inspect", "Criteria")
        self.assertIn("https://github.com/arthexis/gway-remote/issues/41", prompt)
        self.assertIn("Post a comment", prompt)
        self.assertIn("Do not close the issue", prompt)
        self.assertIn("Do not merge or deploy", prompt)

    def test_crash_report_is_bounded_and_does_not_claim_success(self):
        report = diagnostic_body(reason="timeout", phase="executing",
                                 exit_code=-15, elapsed_seconds=97)
        self.assertIn("Reason: timeout", report)
        self.assertIn("Exit code: -15", report)
        self.assertIn("97s", report)
        self.assertIn("remains open", report)
        with self.assertRaises(ValueError):
            diagnostic_body(reason="success")

    def test_failed_delivery_stays_durable_then_retries(self):
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / "outbox.sqlite"
            with ReportOutbox(db) as outbox:
                outbox.enqueue("arthexis/gway-remote", 41, "Crash diagnostic")
                self.assertEqual(outbox.deliver(""), 0)
                self.assertEqual(len(outbox.pending()), 1)
                def offline(request, timeout):
                    raise OSError("offline")
                self.assertEqual(outbox.deliver("token", opener=offline), 0)
            with ReportOutbox(db) as outbox:
                requests = []
                def online(request, timeout):
                    requests.append(request)
                    return Response({"id": 123})
                self.assertEqual(outbox.deliver("token", opener=online), 1)
                self.assertEqual(outbox.pending(), [])
                self.assertEqual(requests[0].get_method(), "POST")
                self.assertEqual(json.loads(requests[0].data)["body"], "Crash diagnostic")


if __name__ == "__main__":
    unittest.main()
