"""Hermetic tests of existing-reader V2 collection and squash CI mapping."""
import copy
import unittest

from gway_remote.development_evidence_v2_collect import collect_v2, _verified_pr_ci
from tests.deployment.test_development_evidence_v2 import fixture, SHA, OTHER, NOW, REPO


def pr(head=SHA):
    return {"number": 633, "merged_at": NOW, "merge_commit_sha": OTHER,
            "base": {"ref": "main", "repo": {"full_name": REPO}},
            "head": {"sha": head, "repo": {"full_name": REPO}}}


def run(head=SHA, status="completed", conclusion="success", number=633):
    return {"id": 42, "event": "pull_request", "head_sha": head,
            "status": status, "conclusion": conclusion,
            "pull_requests": [{"number": number}]}


class Client:
    def __init__(self, *, pulls=None, runs=None, head=OTHER):
        self.head = head
        self.pulls = [pr()] if pulls is None else pulls
        self.runs = [run()] if runs is None else runs
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        if path == f"repos/{REPO}/branches/main":
            return {"commit": {"sha": self.head}}
        if path == f"repos/{REPO}/commits/{self.head}/pulls":
            return self.pulls
        if path == f"repos/{REPO}/actions/runs?event=pull_request&head_sha={SHA}&per_page=100":
            return {"workflow_runs": self.runs}
        raise AssertionError(f"unexpected endpoint {path}")


class CollectTests(unittest.TestCase):
    def test_squash_run_is_bound_without_claiming_same_run_sha(self):
        sample = fixture()
        # Desired main is the squash merge, while PR CI executed on SHA.
        client = Client()
        journal = copy.deepcopy(sample["journal"])
        journal["ocpp-csms"]["sha"] = OTHER
        item = sample["status_report"]["components"][0]
        item["installed_sha"] = OTHER
        item["deployment_evidence"]["activated_revision"] = OTHER
        got = collect_v2("ocpp-csms", client=client, journal_reader=lambda: journal,
                         status_reader=lambda **kw: sample["status_report"],
                         clock=lambda: NOW)
        self.assertEqual(got["stage"], "review")
        self.assertEqual(got["ci"], "success")
        self.assertEqual(got["ci_run"]["id"], 42)
        self.assertEqual(got["ci_run"]["pr_head_sha"], SHA)
        self.assertEqual(got["ci_run"]["main_sha"], OTHER)
        self.assertEqual(got["functional_acceptance"], "unknown")
        self.assertEqual(len(client.paths), 3)

    def test_ambiguous_unknown_or_unbound_ci_is_not_success(self):
        for pulls, runs in (
            ([], [run()]), ([pr(), pr()], [run()]),
            ([pr()], []), ([pr()], [run(number=634)]),
            ([pr()], [run(), run()]), ([pr()], [run(head=OTHER)]),
            ([pr()], [run(status="in_progress", conclusion=None)]),
            ([pr()], [run(conclusion="failure")]),
            ([pr()], [dict(run(), pull_requests=[])]),
            ([pr()], [run()] * 100),
        ):
            client = Client(pulls=pulls, runs=runs)
            result, run_id, pr_head = _verified_pr_ci(client, REPO, OTHER)
            self.assertNotEqual(result, "success" if (pulls, runs) != ([pr()], [run()]) else "invalid")
        client = Client(pulls=[], runs=[run()])
        sample = fixture()
        projected = collect_v2("ocpp-csms", client=client,
                               journal_reader=lambda: sample["journal"],
                               status_reader=lambda **kw: sample["status_report"],
                               clock=lambda: NOW)
        self.assertEqual(projected["stage"], "unknown")
        self.assertIn("ci_not_successful", projected["reasons"])
        self.assertEqual(projected["source_attestation"], "unverified")

    def test_no_extra_permissions_or_mutating_calls(self):
        client = Client()
        sample = fixture()
        collect_v2("ocpp-csms", client=client, journal_reader=lambda: sample["journal"],
                   status_reader=lambda **kw: sample["status_report"], clock=lambda: NOW)
        self.assertTrue(all("/branches/main" in p or "/commits/" in p
                            or "/actions/runs?" in p for p in client.paths))
        self.assertFalse(any("/dispatches" in p for p in client.paths))


if __name__ == "__main__":
    unittest.main()
