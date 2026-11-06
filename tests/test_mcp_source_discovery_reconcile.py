import unittest
from gway_remote.mcp_source_policy import propose_readonly_catalog, classify_source_catalog
from gway_remote.mcp_source_registry import SourceRegistration


class DiscoveryReconcileTests(unittest.TestCase):
    def setUp(self):
        self.registration = SourceRegistration(
            source_id="odoo", revision="a" * 40,
            executable="/opt/odoo-gelectriic/releases/" + "a" * 40 + "/bin/odoo-mcp",
            argv=("/opt/odoo-gelectriic/releases/" + "a" * 40 + "/bin/odoo-mcp",),
            run_as="arthe", enabled=True, permission="read")
        self.read = {"name": "customer_get", "description": "Customer",
                     "inputSchema": {"type": "object"},
                     "annotations": {"readOnlyHint": True, "destructiveHint": False}}
        self.write = {"name": "customer_create", "description": "Create",
                      "inputSchema": {"type": "object"},
                      "annotations": {"readOnlyHint": False, "destructiveHint": False}}

    def test_all_read_tools_discovered_without_name_allowlist(self):
        self.assertEqual([self.read], propose_readonly_catalog(
            self.registration, [self.read, self.write]))

    def test_duplicate_discovered_name_rejected(self):
        with self.assertRaises(ValueError):
            propose_readonly_catalog(self.registration, [self.read, self.read])

    def test_malformed_catalog_rejected(self):
        with self.assertRaises(ValueError):
            propose_readonly_catalog(self.registration, [{"name": "invalid"}])

    def test_read_only_ceiling_excludes_write(self):
        self.assertEqual([], propose_readonly_catalog(self.registration, [self.write]))

    def test_unregistered_source_rejected(self):
        disabled = SourceRegistration(
            source_id="odoo", revision="a" * 40,
            executable=self.registration.executable, argv=self.registration.argv,
            run_as="arthe", enabled=False, permission="read")
        with self.assertRaises(ValueError):
            propose_readonly_catalog(disabled, [self.read])

    def test_execute_tools_are_discovered_but_not_activated(self):
        result = classify_source_catalog(self.registration, [self.read, self.write])
        self.assertEqual(["customer_get"], [t["name"] for t in result["read"]])
        self.assertEqual(["customer_create"], [t["name"] for t in result["execute_required"]])

    def test_missing_annotation_defaults_to_execute_required(self):
        unknown = {"name": "unknown", "inputSchema": {"type": "object"}}
        result = classify_source_catalog(self.registration, [unknown])
        self.assertEqual([], result["read"])
        self.assertEqual([unknown], result["execute_required"])


if __name__ == "__main__":
    unittest.main()
