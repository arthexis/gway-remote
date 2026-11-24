import unittest
from gway_remote.github_health_feed import publish_transitions
from gway_remote.github_health import REPOSITORIES

class GitHubFeedTests(unittest.TestCase):
    def test_only_transition_and_no_branch_data(self):
        repo = next(iter(REPOSITORIES))
        stamp = "2026-11-24T10:00:00Z"
        later = "2026-11-24T11:00:00Z"
        items = []
        sink = lambda build: items.append(build("/test"))
        row = ("private branch", repo, stamp, None, None)
        publish_transitions([row], stamp, sink=sink)
        publish_transitions([row], later, sink=sink)
        publish_transitions([("private branch", repo, stamp, later, "pr_closed")], later, sink=sink)
        self.assertEqual([x["type"] for x in items], ["github.ci_opened", "github.ci_retired"])
        self.assertNotIn("private branch", str(items))
