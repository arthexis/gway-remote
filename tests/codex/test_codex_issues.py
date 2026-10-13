"""GitHub issue state is authoritative, not the worker's exit code."""
import tempfile
import unittest
from pathlib import Path

from gway_remote.codex_issues import DispatchLedger, eligible_issue, ordered_issues, project

REPO = "arthexis/gway-remote"


def issue(number=10, comments=0, state="open", labels=None):
    return {
        "number": number, "title": "Inspect device", "html_url": f"https://github.com/{REPO}/issues/{number}",
        "state": state, "comments": comments,
        "user": {"id": 780437, "login": "arthexis"},
        "labels": [{"name": label} for label in (["local-agent"] if labels is None else labels)],
    }


class IssueProjectionTests(unittest.TestCase):
    def test_queued_sent_attended_and_resend_preserves_total_comments(self):
        with tempfile.TemporaryDirectory() as root, DispatchLedger(Path(root) / "dispatch.db") as ledger:
            task = issue(comments=2)
            self.assertEqual(project(task)["state"], "attended")
            self.assertEqual(project(issue())["state"], "queued")
            with self.assertRaisesRegex(ValueError, "admission"):
                ledger.accept(REPO, task)
            dispatch = ledger.accept(REPO, task, admitted=True)
            self.assertEqual(project(task, dispatch)["state"], "sent")
            self.assertEqual(project(task, dispatch)["comments"], 2)
            self.assertEqual(project(issue(comments=3), dispatch)["state"], "attended")
            with self.assertRaisesRegex(ValueError, "resend"):
                ledger.accept(REPO, issue(comments=3), admitted=True)
            retry = ledger.accept(REPO, issue(comments=3), admitted=True, resend=True)
            self.assertEqual(project(issue(comments=3), retry)["state"], "sent")
            self.assertEqual(project(issue(comments=4), retry)["state"], "attended")
            self.assertEqual(project(issue(comments=4, state="closed"), retry)["state"], "closed")

    def test_creator_label_state_and_repository_are_required(self):
        task = issue()
        self.assertTrue(eligible_issue(task, REPO))
        self.assertFalse(eligible_issue(task, "untrusted/repo"))
        self.assertFalse(eligible_issue(issue(state="closed"), REPO))
        self.assertFalse(eligible_issue(issue(labels=[]), REPO))
        task["user"]["id"] = 123
        self.assertFalse(eligible_issue(task, REPO))

    def test_admission_priority_and_ordering(self):
        with tempfile.TemporaryDirectory() as root, DispatchLedger(Path(root) / "dispatch.db") as ledger:
            low = issue(2, labels=["local-agent", "P3"])
            high = issue(7, labels=["local-agent", "P0"])
            rows = ordered_issues([low, issue(1, state="closed"), high], REPO, ledger)
            self.assertEqual([x["number"] for x in rows], [7, 2])
            with self.assertRaisesRegex(ValueError, "eligible"):
                ledger.accept(REPO, issue(state="closed"), admitted=True)

    def test_unknown_comment_count_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "comment count"):
            project({**issue(), "comments": None})


if __name__ == "__main__":
    unittest.main()
