import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock
from gway_remote.mobile_deploy_follow import snapshot

KEY = "a" * 32


class FollowTests(unittest.TestCase):
    def test_unconfirmed_never_invents_run_or_progress(self):
        out = snapshot({"request_id": KEY}, observer=lambda _: {
            "request_id": KEY, "target": "all", "state": "unconfirmed", "run_id": None},
            client_factory=Mock(side_effect=AssertionError("must not call GitHub")))
        self.assertEqual(out["state"], "unconfirmed")
        self.assertEqual(out["repositories"], [])
        self.assertTrue(out["resumable"])

    def test_bounded_progress_and_bastion_staging_job(self):
        client = Mock()
        def get(path):
            if path.endswith("/jobs?per_page=100"):
                return {"jobs": [
                    {"name": "Deploy gway-bastion (stage-only)", "status": "completed",
                     "conclusion": "success", "steps": [
                         {"number": i, "name": "secret data", "status": "completed", "conclusion": "success"}
                         for i in range(40)]}]}
            return {"id": 42, "event": "workflow_dispatch", "status": "completed", "conclusion": "success"}
        client.get.side_effect = get
        out = snapshot({"request_id": KEY}, observer=lambda _: {
            "request_id": KEY, "target": "gway-bastion", "state": "completed", "run_id": 42},
            client_factory=lambda: client)
        self.assertEqual(out["conclusion"], "success")
        self.assertEqual(out["repositories"][0]["name"], "gway-bastion")
        self.assertEqual(len(out["repositories"][0]["steps"]), 24)
        self.assertNotIn("secret data", str(out))

    def test_appliance_evidence_not_attributed_to_workflow(self):
        with tempfile.TemporaryDirectory() as folder:
            sha = "a" * 40
            filename = "20261021T120000000000Z-gway-bastion-" + sha[:12] + ".log"
            Path(folder, filename).write_text("TASK [secret=PRIVATE]\\nPLAY RECAP\\n")
            client = Mock()
            def get(path):
                if path.endswith("/jobs?per_page=100"):
                    return {"jobs": [{"name": "Deploy gway-bastion (stage-only)", "status": "completed", "conclusion": "success"}]}
                return {"id": 42, "event": "workflow_dispatch", "status": "completed", "conclusion": "success"}
            client.get.side_effect = get
            result = snapshot({"request_id": KEY}, observer=lambda _: {"target": "gway-bastion", "state": "completed", "run_id": 42},
                              client_factory=lambda: client,
                              attempts_reader=lambda: {"gway-bastion": {"sha": sha, "status": "staged", "log": filename}},
                              revision_reader=lambda _: None, log_root=folder)
            row = result["repositories"][0]
            self.assertEqual(row["last_appliance_attempt"]["state"], "staged")
            self.assertFalse(row["last_appliance_attempt"]["associated_with_this_run"])
            self.assertIsNone(row["installed_sha"])
            self.assertNotIn("PRIVATE", str(result))
    def test_rejects_unauthorized_run_identity(self):
        client = Mock()
        client.get.return_value = {"id": 43, "event": "workflow_dispatch"}
        with self.assertRaisesRegex(RuntimeError, "identity_mismatch"):
            snapshot({"request_id": KEY}, observer=lambda _: {
                "request_id": KEY, "target": "ocpp-csms", "state": "running", "run_id": 42},
                client_factory=lambda: client)

    def test_rejects_invalid_request(self):
        for payload in ({}, {"request_id": "../../oops"}, {"request_id": KEY, "force": True}):
            with self.assertRaises(ValueError):
                snapshot(payload)
