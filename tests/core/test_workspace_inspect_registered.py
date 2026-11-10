"""Offline acceptance: inspect only checkout roots from existing node registrations."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gway_remote.mcp_workspace_inspect import inspect_authorized, WorkspaceUnavailable


def git(*argv):
    subprocess.run(["git", *map(str, argv)], check=True,
                   capture_output=True, timeout=5)


def make_checkout(base, name="checkout", origin="https://github.com/arthexis/example.git"):
    checkout = base / name
    checkout.mkdir(parents=True)
    git("init", "-q", checkout)
    git("-C", checkout, "-c", "user.name=Test",
        "-c", "user.email=example@example.invalid", "commit",
        "--allow-empty", "-qm", "initial")
    git("-C", checkout, "remote", "add", "origin", origin)
    return checkout


def declared_checkout(path):
    return SimpleNamespace(enabled=True, deployment={
        "schema": 1, "checkout": str(path), "runner": str(path / "deploy.sh"),
        "revision": "a" * 40,
    })


class RegisteredWorkspaceInspection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = self.root / "registry"
        self.registry.mkdir()
        self.args = {"node": "gway-001", "repository": "arthexis/example"}

    def inspect(self, *, registrations=(), args=None):
        return inspect_authorized(
            self.args if args is None else args, trusted_node="gway-001",
            registry=self.registry, trusted_uid=os.geteuid(),
            discover=lambda: registrations,
        )

    def test_registered_provider_deployment_checkout_observed(self):
        checkout = make_checkout(self.root)
        with patch.dict(os.environ, {"GWAY_WORKSPACE_NODE": "wrong-node",
                                     "GWAY_WORKSPACE_INSPECT_CONFIG": "/does/not/exist"}):
            result = self.inspect(registrations=[declared_checkout(checkout)])
        self.assertEqual(result["git"]["head"]["state"], "observed")
        self.assertEqual(result["git"]["clean_tracked"]["value"], True)
        self.assertEqual(result["repository"], "arthexis/example")
        self.assertEqual(result["node"], "gway-001")
        self.assertEqual(result["ci"]["state"], "unknown")
        self.assertEqual(result["deployment"]["state"], "unknown")

    def test_registered_agentops_workspace_without_new_config(self):
        root = self.root / "agent-workspaces"
        checkout = make_checkout(root / "arthexis", name="example")
        (self.registry / "agentops.repositories").write_text("arthexis/example")
        (self.registry / "agentops.runtime.json").write_text(
            json.dumps({"workspace": str(root), "agent_executable": "/opt/agent"}))
        result = self.inspect()
        self.assertEqual(result["git"]["head"]["state"], "observed")
        self.assertEqual(result["git"]["clean_tracked"]["value"], True)
        self.assertEqual(checkout.name, "example")

    def test_unregistered_repository_is_unknown_and_does_not_scan(self):
        runner = Mock(return_value=())
        with patch("gway_remote.mcp_workspace_inspect.subprocess.run") as subprocess_run:
            result = inspect_authorized(
                self.args, trusted_node="gway-001", registry=self.registry,
                trusted_uid=os.geteuid(), discover=runner)
            subprocess_run.assert_not_called()
        runner.assert_called_once_with()
        self.assertEqual(result["git"]["head"]["state"], "unknown")
        self.assertEqual(result["git"]["head"]["reason"], "repository_not_registered")

    def test_cross_node_rejected_before_any_registry_call(self):
        registrar = Mock(side_effect=AssertionError("registry must not be read"))
        with self.assertRaises(WorkspaceUnavailable):
            inspect_authorized({**self.args, "node": "gway-002"},
                               trusted_node="gway-001", discover=registrar)
        registrar.assert_not_called()

    def test_rejects_traversal_and_caller_paths(self):
        for repo in ("../etc", "arthexis/..", "arthexis/x/y", "/etc/passwd", "", "arthexis/a?b"):
            with self.subTest(repository=repo), self.assertRaises(ValueError):
                self.inspect(args={**self.args, "repository": repo})
        with self.assertRaises(ValueError):
            self.inspect(args={**self.args, "path": "/etc/shadow"})

    def test_wrong_origin_never_reports_git_state(self):
        checkout = make_checkout(self.root, origin="https://github.com/other/repo.git")
        result = self.inspect(registrations=[declared_checkout(checkout)])
        self.assertEqual(result["git"]["head"]["state"], "unknown")
        self.assertEqual(result["git"]["head"]["reason"], "repository_not_registered")

    def test_symlinked_and_world_writable_checkout_denied(self):
        checkout = make_checkout(self.root)
        target = self.root / "alias"
        target.symlink_to(checkout, target_is_directory=True)
        for path in (target, checkout):
            if path == checkout:
                checkout.chmod(0o777)
            with self.subTest(path=path):
                result = self.inspect(registrations=[declared_checkout(path)])
                self.assertEqual(result["git"]["head"]["state"], "unknown")

    def test_ambiguous_registered_checkouts_fail_closed(self):
        first = make_checkout(self.root, "first")
        second = make_checkout(self.root, "second")
        result = self.inspect(registrations=[declared_checkout(first),
                                              declared_checkout(second)])
        self.assertEqual(result["git"]["head"]["state"], "unknown")
        self.assertEqual(result["git"]["head"]["reason"], "ambiguous_registered_checkout")

    def test_broken_or_world_writable_agentops_policy_denied(self):
        p = self.registry / "agentops.repositories"
        p.write_text("arthexis/example")
        p.chmod(0o666)
        self.assertEqual(self.inspect()["git"]["head"]["reason"],
                         "workspace_registry_invalid")
        p.chmod(0o644)
        self.assertEqual(self.inspect()["git"]["head"]["reason"],
                         "workspace_registry_unavailable")

    def test_private_agentops_workspace_unavailable_without_elevation(self):
        root = self.root / "missing"
        (self.registry / "agentops.repositories").write_text("arthexis/example")
        (self.registry / "agentops.runtime.json").write_text(json.dumps({
            "workspace": str(root), "agent_executable": "/opt/agent"}))
        result = self.inspect()
        self.assertEqual(result["git"]["head"]["state"], "unknown")
        self.assertEqual(result["git"]["head"]["reason"],
                         "registered_workspace_unavailable")
        self.assertEqual(result["deployment"]["state"], "unknown")

    def test_git_fsmonitor_command_does_not_execute(self):
        checkout = make_checkout(self.root)
        marker = self.root / "must-not-run"
        git("-C", checkout, "config", "core.fsmonitor",
            "sh -c 'touch " + str(marker) + "'")
        result = self.inspect(registrations=[declared_checkout(checkout)])
        self.assertEqual(result["git"]["head"]["state"], "observed")
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
