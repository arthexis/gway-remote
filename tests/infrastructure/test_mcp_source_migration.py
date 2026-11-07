import unittest

from gway_remote.mcp_source_migration import migrate_policy


class MigrationTests(unittest.TestCase):
    def test_removes_static_tool_catalog(self):
        old = {"version": 1, "sources": [
            {"registration": {"source_id": "odoo", "enabled": True},
             "tools": [{"name": "customer_search"}]}]}
        self.assertEqual(migrate_policy(old), {"version": 2, "sources": [
            {"registration": {"source_id": "odoo", "enabled": True}}]})
        self.assertIn("tools", old["sources"][0])

    def test_idempotent(self):
        policy = {"version": 2, "sources": [{"registration": {"source_id": "odoo"}}]}
        self.assertEqual(migrate_policy(policy), policy)

    def test_rejects_unexpected_fields(self):
        with self.assertRaises(ValueError):
            migrate_policy({"version": 1, "sources": [
                {"registration": {}, "tools": [], "remote_user": "root"}]})


if __name__ == "__main__":
    unittest.main()
