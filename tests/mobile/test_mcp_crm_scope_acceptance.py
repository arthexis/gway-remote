"""Hermetic tests for the fixed live CRM scope acceptance client."""
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch

M = runpy.run_path(str(Path(__file__).resolve().parents[2] /
                       "scripts/mcp-crm-scope-acceptance.py"))
CHECK = M["check"]
ERROR = M["AcceptanceError"]
RID = "a" * 32
CHALLENGE = 'Bearer scope="gway:execute", error="insufficient_scope"'


class CRMNativeScopeAcceptanceTests(unittest.TestCase):
    def fixture(self, *, fail_tool=None, changed=False):
        calls = []
        def invoke(token, name, args):
            calls.append((token, name, args))
            if name == M["RECEIPT"]:
                import json
                count = sum(c[1] == name for c in calls)
                receipt = {"request_id": RID, "status": "completed",
                           "id": 5 if changed and count == 3 else 4}
                return 200, "", {"content": [
                    {"type": "text", "text": json.dumps(receipt)}]}
            if name == M["DIAGNOSTIC"]:
                if token == "read":
                    return 200, "", {"isError": True,
                        "_meta": {"mcp/www_authenticate": [CHALLENGE]}}
                return 200, "", {"content": [{"type": "text", "text": "{}"}]}
            self.assertEqual(token, "read")
            self.assertEqual(args, {})
            if name == fail_tool:
                return 403, "", {}
            return 401, CHALLENGE, {}
        return calls, invoke

    def test_success_checks_all_denials_and_unchanged_shared_receipt(self):
        calls, invoke = self.fixture()
        self.assertEqual(CHECK("read", "execute", RID, invoke=invoke), {
            "scope_isolation": "passed", "crm_denials": 3,
            "shared_receipt_read": "passed", "principal_ownership": "not_applicable",
            "mutation_payloads": 0})
        self.assertEqual([c[1] for c in calls if c[1] in M["WRITES"]],
                         list(M["WRITES"]))
        self.assertEqual(len(calls), 8)

    def test_generic_rejection_does_not_prove_scope(self):
        for tool in M["WRITES"]:
            _, invoke = self.fixture(fail_tool=tool)
            with self.assertRaisesRegex(ERROR, "crm_scope_denial_not_verified"):
                CHECK("read", "execute", RID, invoke=invoke)

    def test_changed_receipt_fails_closed(self):
        _, invoke = self.fixture(changed=True)
        with self.assertRaisesRegex(ERROR, "receipt_changed"):
            CHECK("read", "execute", RID, invoke=invoke)

    def test_distinct_credentials_required_before_network(self):
        calls, invoke = self.fixture()
        with self.assertRaises(ERROR):
            CHECK("read", "read", RID, invoke=invoke)
        self.assertEqual(calls, [])

    def test_transport_refuses_any_nonempty_mutation_payload(self):
        for tool in M["WRITES"]:
            with self.assertRaisesRegex(ERROR, "unsafe_payload"):
                M["call"]("read", tool, {"request_id": RID})
        with self.assertRaisesRegex(ERROR, "unapproved_tool"):
            M["call"]("read", "node_exec", {})

    def test_redirects_not_followed(self):
        self.assertIsNone(M["NoRedirect"]().redirect_request(
            None, None, 302, "", {}, "https://example.org"))
