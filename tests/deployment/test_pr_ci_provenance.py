"""PR-only deployment provenance: fail closed without exact merged PR and passing checks."""
import unittest
from gway_remote.github_state import ci_for_head

REPO = "arthexis/gway-ap-kiosk"
MAIN = "a" * 40
HEAD = "b" * 40


class FakeClient:
    def __init__(self, pulls, runs):
        self.pulls = pulls
        self.runs = runs

    def get(self, path):
        if path.endswith("/pulls"):
            return self.pulls
        if "actions/runs?" in path:
            assert f"head_sha={HEAD}" in path
            assert "event=pull_request" in path
            return {"workflow_runs": self.runs}
        raise AssertionError(path)


def merged_pr(**changes):
    result = {
        "number": 17, "merged_at": "2026-10-20T18:00:00Z",
        "merge_commit_sha": MAIN,
        "base": {"ref": "main", "repo": {"full_name": REPO}},
        "head": {"sha": HEAD, "repo": {"full_name": REPO}},
    }
    result.update(changes)
    return result


def run(status="completed", conclusion="success", **changes):
    result = {
        "event": "pull_request", "head_sha": HEAD,
        "status": status, "conclusion": conclusion,
        "pull_requests": [{"number": 17}],
    }
    result.update(changes)
    return result


class PRCIDeployTests(unittest.TestCase):
    def test_exact_merged_pr_success(self):
        self.assertEqual(ci_for_head(FakeClient([merged_pr()], [run()]), REPO, MAIN), "success")
        self.assertEqual(ci_for_head(FakeClient([merged_pr()], [run(pull_requests=[])]), REPO, MAIN), "success")

    def test_fails_closed_when_provenance_missing_or_ambiguous(self):
        cases = [
            [], [merged_pr(merge_commit_sha="c" * 40)],
            [merged_pr(base={"ref": "other", "repo": {"full_name": REPO}})],
            [merged_pr(), merged_pr()],
        ]
        for pulls in cases:
            with self.subTest(pulls=pulls):
                self.assertEqual(ci_for_head(FakeClient(pulls, [run()]), REPO, MAIN), "unknown")

    def test_only_exact_pr_head_ci_is_eligible(self):
        for runs in ([], [run(head_sha="c" * 40)], [run(event="push")],
                     [run(pull_requests=[{"number": 18}])]):
            with self.subTest(runs=runs):
                self.assertEqual(ci_for_head(FakeClient([merged_pr()], runs), REPO, MAIN), "unknown")

    def test_pending_and_failure_block(self):
        for runs, expected in [
            ([run(status="in_progress", conclusion=None)], "pending"),
            ([run(conclusion="failure")], "failure"),
            ([run(), run(conclusion="failure")], "failure"),
        ]:
            with self.subTest(expected=expected):
                self.assertEqual(ci_for_head(FakeClient([merged_pr()], runs), REPO, MAIN), expected)


if __name__ == "__main__":
    unittest.main()
