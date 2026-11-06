import unittest
from gway_remote.mcp_source_policy import propose_readonly_catalog
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

    def test_only_explicit_read_catalog_is_proposed(self):
        self.assertEqual([self.read], propose_readonly_catalog(
            self.registration, [self.read, self.write], ["customer_get"]))

    def test_write_is_rejected_even_if_named(self):
        with self.assertRaises(ValueError):
            propose_readonly_catalog(self.registration, [self.read, self.write], ["customer_create"])

    def test_missing_or_duplicate_approval_fails_closed(self):
        for names in (["unknown"], ["customer_get", "customer_get"], []):
            with self.subTest(names=names), self.assertRaises(ValueError):
                propose_readonly_catalog(self.registration, [self.read], names)

    def test_duplicate_discovered_name_rejected(self):
        with self.assertRaises(ValueError):
            propose_readonly_catalog(self.registration, [self.read, self.read], ["customer_get"])

    def test_annotation_is_not_authority(self):
        with self.assertRaises(ValueError):
            propose_readonly_catalog(self.registration, [self.read], ["customer_get", "customer_create"])


if __name__ == "__main__":
    unittest.main()
