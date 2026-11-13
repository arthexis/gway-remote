"""Deployment inventory must never confuse attempts with installed revisions."""
import unittest
from unittest.mock import patch
from gway_remote.deployments import inventory, format_inventory


class FakeGitHub:
    def get(self, path):
        return {"commit": {"sha": "abcdef123456" + "0" * 28}}


class DeploymentInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hostname_patch = patch("gway_remote.deployments.socket.gethostname", return_value="gway-001")
        cls.hostname_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.hostname_patch.stop()

    @patch("gway_remote.deployments.main_head", return_value="abcdef123456" + "0" * 28)
    def test_unknown_installed_not_assumed_from_successful_attempt(self, head):
        report = inventory("ocpp-csms", node="gway-001", policy={"ocpp-csms"}, client=FakeGitHub(),
                           attempts={"ocpp-csms": {"sha": "abcdef123456" + "0" * 28,
                               "status": "installed", "at": "2026-10-17T10:00:00+00:00"}},
                           installed=lambda _: None)
        row = report["components"][0]
        self.assertEqual(row["revision_status"], "unknown")
        self.assertIsNone(row["installed_sha"])
        self.assertEqual(row["attempt_status"], "installed")
        self.assertEqual(row["attempted_at"], "2026-10-17T10:00:00+00:00")
        self.assertIn("unknown", format_inventory(report))

    @patch("gway_remote.deployments.main_head", return_value="abcdef123456" + "0" * 28)
    def test_current_and_behind(self, head):
        current = inventory("ocpp-csms", node="gway-001", policy={"ocpp-csms"}, client=FakeGitHub(), attempts={},
                            installed=lambda _: "abcdef123456")
        self.assertEqual(current["components"][0]["revision_status"], "current")
        behind = inventory("ocpp-csms", node="gway-001", policy={"ocpp-csms"}, client=FakeGitHub(), attempts={},
                           installed=lambda _: "111111111111")
        self.assertEqual(behind["components"][0]["revision_status"], "behind")

    def test_invalid_repository(self):
        with self.assertRaises(ValueError):
            inventory("unlisted-repo", client=FakeGitHub(), attempts={})


class BastionInventoryPresentationTests(unittest.TestCase):
    SHA = "abcdef123456" + "0" * 28
    OTHER = "b" * 40

    @staticmethod
    def _no_other_probe(name):
        raise AssertionError(f"unexpected local installed probe: {name}")

    def snapshot(self, evidence, *, node="gway-001", attempts=None):
        with patch("gway_remote.deployments.socket.gethostname", return_value="gway-001"), \
             patch("gway_remote.deployments.main_head", return_value=self.SHA), \
             patch("gway_remote.deployments.read_bastion_evidence",
                   return_value=evidence) as read:
            result = inventory(
                "gway-bastion", node=node, policy={"gway-bastion"},
                client=FakeGitHub(), attempts=attempts or {},
                installed=self._no_other_probe,
            )
            if node == "gway-001":
                read.assert_called_once_with()
            else:
                read.assert_not_called()
        return result, result["components"][0], format_inventory(result)

    def test_staged_only_is_visible_but_never_installed(self):
        report, row, output = self.snapshot({
            "release_state": "staged", "staged_sha": self.SHA,
            "activated_sha": None, "runtime": "not_applicable",
            "evidence": "verified",
        }, attempts={"gway-bastion": {"sha": self.SHA, "status": "installed"}})
        self.assertEqual(row["installed"], "unknown")
        self.assertIsNone(row["installed_sha"])
        self.assertEqual(row["revision_status"], "unknown")
        self.assertEqual(row["release_state"], "staged")
        self.assertEqual(row["staged_sha"], self.SHA)
        self.assertEqual(row["release_evidence"], "verified")
        self.assertIn("Bastion release: staged (verified release metadata)", output)
        self.assertIn("Staged SHA: " + self.SHA, output)
        self.assertIn("Activated/installed revision: unknown", output)
        self.assertIn("comparison to main: unknown", output)
        self.assertIn("Runtime health: unverified", output)
        self.assertNotIn("Activated/installed SHA:", output)
        self.assertTrue(report["local_evidence"])

    def test_activated_metadata_does_not_claim_runtime_health(self):
        _, row, output = self.snapshot({
            "release_state": "activated", "staged_sha": self.OTHER,
            "activated_sha": self.SHA, "runtime": "unknown",
            "evidence": "verified",
        })
        self.assertEqual(row["installed_sha"], self.SHA)
        self.assertEqual(row["installed"], "verified")
        self.assertEqual(row["revision_status"], "current")
        self.assertIn("Bastion release: activated (verified release metadata)", output)
        self.assertIn("Staged SHA: " + self.OTHER, output)
        self.assertIn("Activated/installed SHA: " + self.SHA, output)
        self.assertIn("comparison to main: current", output)
        self.assertIn("Runtime health: unknown (no independent runtime probe)", output)

    def test_absent_and_invalid_fail_closed(self):
        for kind in ("missing", "invalid"):
            with self.subTest(evidence=kind):
                _, row, output = self.snapshot({
                    "release_state": "unknown", "staged_sha": None,
                    "activated_sha": None, "runtime": "unknown",
                    "evidence": kind,
                })
                self.assertIsNone(row["installed_sha"])
                self.assertEqual(row["revision_status"], "unknown")
                self.assertEqual(row["release_evidence"], kind)
                self.assertIn(f"Bastion release: unknown ({kind} evidence)", output)
                self.assertIn("comparison to main: unknown", output)
                self.assertNotIn("Activated/installed SHA:", output)

    def test_remote_node_does_not_consume_local_bastion_evidence(self):
        report, row, output = self.snapshot({
            "release_state": "activated", "staged_sha": self.OTHER,
            "activated_sha": self.SHA, "runtime": "healthy",
            "evidence": "verified",
        }, node="gway-004")
        self.assertFalse(report["local_evidence"])
        self.assertIsNone(row["release_state"])
        self.assertIsNone(row["staged_sha"])
        self.assertIsNone(row["release_evidence"])
        self.assertIsNone(row["installed_sha"])
        self.assertEqual(row["revision_status"], "unknown")
        self.assertIn("remote node; local evidence not used", output)
        self.assertNotIn(self.OTHER, output)
        self.assertNotIn("Runtime health: healthy", output)


if __name__ == "__main__":
    unittest.main()
