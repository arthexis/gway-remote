import json
import unittest

from gway_remote.mcp_source_reconcile import build_readonly_source_entry, policy_payload, reconcile_sources
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

    def test_failed_source_is_isolated(self):
        other = SourceRegistration("other", "b" * 40,
            "/opt/other/releases/" + "b" * 40 + "/bin/mcp",
            ("/opt/other/releases/" + "b" * 40 + "/bin/mcp",),
            "other", True, "read")

        def discover(registration):
            if registration.source_id == "other":
                raise RuntimeError("offline")
            return [self.read, self.write]

        result = reconcile_sources([other, self.registration], discover=discover)
        sources = json.loads(result["policy"])["sources"]
        self.assertEqual(["odoo"], [x["registration"]["source_id"] for x in sources])
        self.assertEqual({"other": "RuntimeError"}, result["failures"])
        self.assertEqual(("customer_create",), result["execute_required"]["odoo"])
        self.assertEqual(result["sha256"], policy_payload(sources)[1])

    def test_disabled_source_not_discovered(self):
        from dataclasses import replace
        disabled = replace(self.registration, enabled=False)
        result = reconcile_sources([disabled], discover=lambda _: self.fail("unexpected discovery"))
        self.assertEqual([], json.loads(result["policy"])["sources"])


if __name__ == "__main__":
    unittest.main()
