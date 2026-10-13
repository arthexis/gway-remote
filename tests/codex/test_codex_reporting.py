"""Issue-first assignment reporting tests (all GitHub operations mocked)."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from gway_remote.codex_reporting import ReportOutbox, assignment_prompt, diagnostic_body, record_interrupted
from gway_remote.codex_queue import TaskQueue


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

    def test_restart_recovery_posts_one_diagnostic_per_interrupted_attempt(self):
        with tempfile.TemporaryDirectory() as root:
            with TaskQueue(Path(root) / "queue.sqlite") as queue, \
                 ReportOutbox(Path(root) / "reports.sqlite") as outbox:
                task = queue.admit("field-validation", "arthexis/gway-remote", 41)
                queue.approve(task["id"])
                claimed = queue.claim_next()
                self.assertEqual(claimed["id"], task["id"])
                self.assertEqual(record_interrupted(queue, outbox), 1)
                self.assertEqual(queue.get(task["id"])["state"], "interrupted")
                self.assertEqual(len(outbox.pending()), 1)
                self.assertEqual(record_interrupted(queue, outbox), 0)
                self.assertEqual(len(outbox.pending()), 1)

    def test_idempotent_attempt_key_and_remote_comment_check(self):
        with tempfile.TemporaryDirectory() as root:
            with ReportOutbox(Path(root) / "reports.sqlite") as outbox:
                first = outbox.enqueue("arthexis/gway-remote", 41,
                                       "Interrupted", report_key="attempt-1")
                second = outbox.enqueue("arthexis/gway-remote", 41,
                                        "Interrupted", report_key="attempt-1")
                self.assertEqual(first, second)
                self.assertEqual(len(outbox.pending()), 1)
                calls = []
                def already_sent(request, timeout):
                    calls.append(request.get_method())
                    return Response([{"body": "<!-- gway-remote-report:attempt-1 -->"}])
                self.assertEqual(outbox.deliver("token", opener=already_sent), 1)
                self.assertEqual(calls, ["GET"])
                self.assertFalse(outbox.pending())

    def test_missing_marker_posts_once(self):
        with tempfile.TemporaryDirectory() as root:
            with ReportOutbox(Path(root) / "reports.sqlite") as outbox:
                outbox.enqueue("arthexis/gway-remote", 41,
                               "Interrupted", report_key="attempt-2")
                calls = []
                def deliver(request, timeout):
                    calls.append(request.get_method())
                    if request.get_method() == "GET":
                        return Response([])
                    body = json.loads(request.data)["body"]
                    self.assertIn("gway-remote-report:attempt-2", body)
                    return Response({"id": 51})
                self.assertEqual(outbox.deliver("token", opener=deliver), 1)
                self.assertEqual(calls, ["GET", "POST"])
                self.assertFalse(outbox.pending())

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
