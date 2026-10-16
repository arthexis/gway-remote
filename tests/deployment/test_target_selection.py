"""Behavioral tests for explicit per-repository appliance deployments."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gway_remote.best_effort import execute
from gway_remote.reconcile import TARGETS

SHA = "a" * 40


class TargetSelectionTests(unittest.TestCase):
    def test_one_target_does_not_install_other_repositories(self):
        calls = []
        installers = {name: lambda sha, name=name: calls.append((name, sha))
                      for name, _ in TARGETS}
        with tempfile.TemporaryDirectory() as directory:
            with patch("gway_remote.best_effort.main_head", return_value=SHA):
                result = execute(object(), None, installers, directory=Path(directory),
                                 deploy_all=True, target="gway-lcd-sound")
        self.assertEqual("completed", result["decision"])
        self.assertEqual([("gway-lcd-sound", SHA)], calls)
        self.assertEqual(["gway-lcd-sound"], [x["name"] for x in result["results"]])

    def test_unknown_target_is_rejected_before_any_install(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "unknown deployment target"):
                execute(object(), None, {}, directory=Path(directory),
                        deploy_all=True, target="unknown")

    def test_target_requires_explicit_all_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "requires explicit"):
                execute(object(), None, {}, directory=Path(directory),
                        target="ocpp-csms")
