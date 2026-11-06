import json
import unittest

from gway_remote.mcp_source_reconcile import build_readonly_source_entry, policy_payload
from gway_remote.mcp_source_registry import SourceRegistration


class SourceReconcileTests(unittest.TestCase):
    def setUp(self):
        path = "/opt/odoo-gelectriic/releases/" + "a" * 40 + "/bin/odoo-mcp"
        self.registration = SourceRegistration("odoo", "a" * 40, path, (path,), "arthe", True, "read")
        self.read = {"name": "customer_get", "inputSchema": {"type": "object"},
                     "annotations": {"readOnlyHint": True, "destructiveHint": False}}
        self.write = {"name": "customer_create", "inputSchema": {"type": "object"},
                      "annotations": {"readOnlyHint": False}}

    def test_read_published_write_classified(self):
        entry, pending = build_readonly_source_entry(
            self.registration, discover=lambda _: [self.write, self.read])
        self.assertEqual(["customer_get"], [x["name"] for x in entry["tools"]])
        self.assertEqual(("customer_create",), pending)
        self.assertEqual(self.registration.revision, entry["registration"]["revision"])

    def test_digest_is_stable(self):
        entry, _ = build_readonly_source_entry(self.registration, discover=lambda _: [self.read])
        payload, digest = policy_payload([entry])
        self.assertEqual(payload, policy_payload([entry])[0])
        self.assertEqual(json.loads(payload)["sources"][0], entry)
        self.assertEqual(len(digest), 64)

    def test_duplicate_source_denied(self):
        entry, _ = build_readonly_source_entry(self.registration, discover=lambda _: [self.read])
        with self.assertRaises(ValueError):
            policy_payload([entry, entry])

    def test_discovery_failure_is_not_silently_ignored(self):
        def fail(_):
            raise RuntimeError("provider offline")
        with self.assertRaises(RuntimeError):
            build_readonly_source_entry(self.registration, discover=fail)


if __name__ == "__main__":
    unittest.main()
