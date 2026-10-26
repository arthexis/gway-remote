"""Deployment dispatch rejects unsupported nodes before contacting GitHub."""
import subprocess
import unittest
from unittest.mock import patch

from gway_remote.deploy_dispatch import dispatch


class DispatchNodeTests(unittest.TestCase):
    def test_unsupported_node_never_dispatches(self):
        for node in ("gway-002", "gway-004", "gway-005", "customer.gelectriic.com", "unknown"):
            with self.subTest(node=node), patch("gway_remote.deploy_dispatch.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "not approved"):
                    dispatch("all", node=node)
                run.assert_not_called()

    def test_default_node_is_explicit_in_dispatch(self):
        result = subprocess.CompletedProcess([], 0, "{}", "")
        with patch("gway_remote.deploy_dispatch.subprocess.run", return_value=result) as run:
            dispatch("all")
            command = run.call_args.args[0]
            self.assertIn("inputs[node]=gway-001", command)
            self.assertIn("inputs[repository]=all", command)

    def test_unknown_repository_never_dispatches(self):
        with patch("gway_remote.deploy_dispatch.subprocess.run") as run:
            with self.assertRaises(ValueError):
                dispatch("unapproved", node="gway-001")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
