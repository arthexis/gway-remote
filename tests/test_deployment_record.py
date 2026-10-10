"""Deployment writer recovery and safety tests."""
import unittest

from gway_remote.deployment_record import record_deployment


class Client:
    def __init__(self):
        self.deployments = []
        self.statuses = {}
        self.posts = []

    def get(self, path):
        if "/statuses?" in path:
            ident = int(path.split("/deployments/")[1].split("/")[0])
            return self.statuses.get(ident, [])
        return self.deployments

    def post(self, path, payload):
        self.posts.append((path, payload))
        if path.endswith("/deployments"):
            ident = len(self.deployments) + 1
            self.deployments.insert(0, {"id": ident, "sha": payload["ref"]})
            return {"id": ident}
        ident = int(path.split("/deployments/")[1].split("/")[0])
        self.statuses[ident] = [payload]
        return {}


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.sha = "a" * 40

    def test_record_once_and_retry_without_duplicates(self):
        verify = lambda name, sha: True
        self.assertEqual(record_deployment(self.client, "ocpp-csms", self.sha, verify), 1)
        self.assertEqual(record_deployment(self.client, "ocpp-csms", self.sha, verify), 1)
        self.assertEqual(len(self.client.posts), 2)

    def test_refuse_unverified(self):
        with self.assertRaises(RuntimeError):
            record_deployment(self.client, "ocpp-csms", self.sha, lambda *args: False)
        self.assertFalse(self.client.posts)

    def test_resume_after_status_failure(self):
        self.client.deployments = [{"id": 9, "sha": self.sha}]
        record_deployment(self.client, "ocpp-csms", self.sha, lambda *args: True)
        self.assertEqual(len(self.client.deployments), 2)
        self.assertEqual(self.client.statuses[2][0]["state"], "success")

    def test_invalid_sha(self):
        with self.assertRaises(ValueError):
            record_deployment(self.client, "ocpp-csms", "bad", lambda *args: True)


if __name__ == "__main__":
    unittest.main()
