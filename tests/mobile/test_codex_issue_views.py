"""R3 GitHub issue projection is read-only and preserves cumulative replies."""
import tempfile
import unittest
from pathlib import Path

from gway_remote.codex_issue_views import list_assignments
from gway_remote.codex_issues import DispatchLedger

REPO = "arthexis/gway-remote"


def issue(number, comments=0):
    return {
        "number": number, "state": "open", "title": "Inspect",
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "comments": comments,
        "labels": [{"name": "local-agent"}],
        "user": {"login": "arthexis", "id": 780437},
    }


class MobileIssueTests(unittest.TestCase):
    def test_queued_sent_attended_and_cumulative_comments(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "dispatch.sqlite"
            items = [issue(41, 2), issue(57)]
            def fetch(repo, token):
                return items if repo == REPO else []
            with DispatchLedger(path) as ledger:
                ledger.accept(REPO, items[0], admitted=True)
            rows = list_assignments(token="test", ledger_path=path, fetcher=fetch)["issues"]
            sent = next(row for row in rows if row["number"] == 41)
            self.assertEqual(sent["state"], "sent")
            self.assertEqual(sent["comments"], 2)
            self.assertTrue(sent["sent_at"])
            self.assertEqual(next(row for row in rows if row["number"] == 57)["state"], "queued")
            items[0]["comments"] = 3
            attended = list_assignments(token="test", ledger_path=path, fetcher=fetch)["issues"][0]
            self.assertEqual(attended["state"], "attended")
            self.assertEqual(attended["comments"], 3)
            self.assertEqual(attended["url"], f"https://github.com/{REPO}/issues/41")

    def test_missing_token_and_failed_fetch_do_not_return_old_local_results(self):
        with self.assertRaisesRegex(RuntimeError, "github_token"):
            list_assignments(token="")
        with tempfile.TemporaryDirectory() as root:
            def offline(repo, token):
                raise OSError("offline")
            with self.assertRaises(OSError):
                list_assignments(token="test", ledger_path=Path(root)/"dispatch.sqlite",
                                 fetcher=offline)
