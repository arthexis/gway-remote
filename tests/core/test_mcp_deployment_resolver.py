"""Negative authorization coverage for node-owned deployment discovery."""
import unittest
from gway_remote.mcp_deployment_resolver import resolve_deployment
from gway_remote.mcp_source_registry import SourceRegistration

SHA = "a" * 40
DEPLOY = dict(schema=1, checkout="/opt/managed/agentops",
              runner="/opt/managed/agentops/deploy.sh", run_as="arthe", revision=SHA)


def source(name="agentops", enabled=True, deployment=DEPLOY):
    return SourceRegistration(source_id=name, revision=SHA,
        executable="/opt/agentops/mcp", argv=("/opt/agentops/mcp",),
        run_as="arthe", enabled=enabled, deployment=deployment)


class ResolverTests(unittest.TestCase):
    def test_registered_provider(self):
        self.assertEqual(resolve_deployment("agentops", discover=lambda: (source(),)), DEPLOY)

    def test_unregistered_disabled_legacy_and_duplicate_denied(self):
        for sources in ((), (source(enabled=False),), (source(deployment=None),),
                        (source(), source())):
            with self.subTest(sources=sources), self.assertRaises(PermissionError):
                resolve_deployment("agentops", discover=lambda: sources)

    def test_path_and_identifier_injection_denied(self):
        for name in ("../../etc/passwd", "agentops;id", "", "agentops/deploy"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                resolve_deployment(name, discover=lambda: (source(),))


if __name__ == "__main__":
    unittest.main()
