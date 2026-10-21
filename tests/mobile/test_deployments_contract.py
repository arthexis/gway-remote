import unittest
from unittest.mock import patch

from gway_remote import mobile_deployments
from gway_remote.mobile import commands, execute
from gway_remote.reconcile import TARGETS


class MobileDeploymentsContractTests(unittest.TestCase):
    def test_read_only_contracts_advertised(self):
        advertised = {command["name"]: command for command in commands()}
        for name in ("deployments-overview", "deployments-progress", "deployments-validate"):
            self.assertTrue(advertised[name]["read_only"])
        self.assertEqual(advertised["deployments-validate"]["arguments"]["target"]["choices"],
                         ["all"] + [name for name, _ in TARGETS])

    def test_selection_is_strict_and_has_no_dispatch(self):
        for target in ("all", *(name for name, _ in TARGETS)):
            self.assertTrue(execute("deployments-validate", {"target": target})["valid"])
        for arguments in ({}, {"target": "gway-remote"}, {"target": "all", "force": True},
                          {"target": 1}, {"target": "../evil"}, {"target": "all;rm -rf /"}):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    execute("deployments-validate", arguments)

    def test_overview_does_not_conflate_staged_and_installed(self):
        with patch.object(mobile_deployments, "read_attempts", return_value={}) as attempts:
            output = mobile_deployments.overview({}, attempts_reader=lambda: {
                "gway-bastion": {"status": "staged", "sha": "a" * 40,
                                 "at": "2026-10-21T11:00:00+00:00"}
            }, revision_reader=lambda name: None)
        attempts.assert_not_called()
        bastion = next(x for x in output["targets"] if x["name"] == "gway-bastion")
        self.assertEqual(bastion["last_attempt"]["status"], "staged")
        self.assertIsNone(bastion["installed_sha"])
        self.assertIsNone(output["controller"]["last_successful_update"])
        self.assertEqual(len(output["targets"]), len(TARGETS))

    def test_progress_is_explicitly_unknown_until_run_tracking_exists(self):
        self.assertEqual(execute("deployments-progress", {})["state"], "unknown")
        self.assertFalse(execute("deployments-progress", {})["resumable"])
        with self.assertRaises(ValueError):
            execute("deployments-progress", {"run_id": "guessed"})


if __name__ == "__main__":
    unittest.main()
