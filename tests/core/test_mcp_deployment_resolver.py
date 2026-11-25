"""Negative authorization coverage for node-owned deployment discovery."""
import unittest
from unittest.mock import patch
from gway_remote.mcp_deployment_resolver import deployment_catalog, resolve_deployment
from gway_remote.mcp_source_registry import SourceRegistration

SHA = "a" * 40
DEPLOY = dict(schema=1, checkout="/opt/managed/agentops",
              runner="/opt/managed/agentops/deploy.sh", revision=SHA)


def source(name="agentops", enabled=True, deployment=DEPLOY):
    return SourceRegistration(source_id=name, revision=SHA,
        executable="/opt/agentops/mcp", argv=("/opt/agentops/mcp",),
        run_as="arthe", enabled=enabled, deployment=deployment)


class ResolverTests(unittest.TestCase):
    def test_catalog_is_bounded_path_free_and_uses_target_pin(self):
        target = dict(DEPLOY, revision="b" * 40)
        rows = deployment_catalog(discover=lambda: (
            source("lcd_sound", deployment=None), source(deployment=target),
            source("repo", enabled=False)))
        self.assertEqual(rows, [
            {"application": "agentops", "alias": "gway-agent-ops",
             "revision": "b" * 40, "status": "declared"},
            {"application": "lcd_sound", "alias": "gway-lcd-sound",
             "revision": None, "status": "no_declaration"},
            {"application": "repo", "alias": None,
             "revision": None, "status": "not_enabled"}])
        self.assertNotIn("/opt/", repr(rows))

    def test_catalog_rejects_duplicates_and_alias_collisions(self):
        with self.assertRaises(PermissionError):
            deployment_catalog(discover=lambda: (source(), source()))
        with patch("gway_remote.mcp_deployment_resolver.APPLICATION_ALIASES",
                   {"first-alias": "agentops", "second-alias": "agentops"}):
            with self.assertRaises(PermissionError):
                deployment_catalog(discover=lambda: (source(),))

    def test_catalog_marks_mutated_declaration_invalid_without_leaking_it(self):
        declaration = dict(DEPLOY)
        registration = source(deployment=declaration)
        declaration["revision"] = "private-invalid-value"
        row = deployment_catalog(discover=lambda: (registration,))[0]
        self.assertEqual((row["status"], row["revision"]), ("declaration_invalid", None))
        self.assertNotIn("private-invalid-value", repr(row))

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
