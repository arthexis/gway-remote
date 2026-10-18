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
            with patch("gway_remote.best_effort.main_head", return_value=SHA), \
             patch("gway_remote.best_effort.ci_for_head", return_value="success"):
                result = execute(object(), None, installers, directory=Path(directory),
                                 deploy_all=True, target="gway-lcd-sound")
        self.assertEqual("completed", result["decision"])
        self.assertEqual([("gway-lcd-sound", SHA)], calls)
        self.assertEqual(["gway-lcd-sound"], [x["name"] for x in result["results"]])

    def test_all_continues_when_one_ci_fails(self):
        calls = []
        names = [name for name, _ in TARGETS]
        installers = {name: lambda sha, name=name: calls.append(name) for name in names}
        with tempfile.TemporaryDirectory() as directory, \
             patch("gway_remote.best_effort.main_head", return_value=SHA), \
             patch("gway_remote.best_effort.ci_for_head", side_effect=[
                 "failure", *(["success"] * (len(names) - 1))]):
            result = execute(object(), None, installers, directory=Path(directory), deploy_all=True)
        self.assertEqual(result["decision"], "partial")
        self.assertEqual(result["results"][0]["status"], "blocked")
        self.assertIn("CI failure", result["results"][0]["reason"])
        self.assertEqual(calls, names[1:])

    def test_all_continues_after_install_failure(self):
        names = [name for name, _ in TARGETS]
        calls = []
        def installer(sha, name):
            calls.append(name)
            if name == names[0]:
                raise RuntimeError("installer failed")
        installers = {name: lambda sha, name=name: installer(sha, name) for name in names}
        with tempfile.TemporaryDirectory() as directory, \
             patch("gway_remote.best_effort.main_head", return_value=SHA), \
             patch("gway_remote.best_effort.ci_for_head", return_value="success"):
            result = execute(object(), None, installers, directory=Path(directory), deploy_all=True)
        self.assertEqual(result["decision"], "partial")
        self.assertEqual(result["results"][0]["status"], "failed")
        self.assertEqual(calls, names)

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
