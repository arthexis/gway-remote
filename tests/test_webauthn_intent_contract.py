import unittest

from gway_remote.webauthn_intent_contract import (
    MCP_SCOPES, MAX_LIFETIME_SECONDS, admin_intent_digest,
    canonical_admin_intent,
)


class WebAuthnIntentContractTest(unittest.TestCase):
    def setUp(self):
        self.issue = {
            "action": "issue_mcp_bearer",
            "scopes": ["gway:read", "gway:execute"],
            "lifetime_seconds": 86400,
            "request_id": "a" * 32,
        }

    def rejects(self, **changes):
        payload = dict(self.issue, **changes)
        with self.assertRaises(ValueError):
            canonical_admin_intent(payload)

    def test_canonical_order_and_digest_are_stable(self):
        expected = canonical_admin_intent(self.issue)
        reordered = dict(reversed(list(self.issue.items())))
        reordered["scopes"] = list(reversed(self.issue["scopes"]))
        self.assertEqual(expected, canonical_admin_intent(reordered))
        self.assertEqual(admin_intent_digest(self.issue), admin_intent_digest(reordered))
        self.assertEqual(len(admin_intent_digest(self.issue)), 32)
        self.assertEqual(MCP_SCOPES, ("gway:execute", "gway:read"))

    def test_alterations_change_bound_digest(self):
        altered = dict(self.issue, lifetime_seconds=3600)
        self.assertNotEqual(admin_intent_digest(self.issue), admin_intent_digest(altered))
        altered = dict(self.issue, request_id="b" * 32)
        self.assertNotEqual(admin_intent_digest(self.issue), admin_intent_digest(altered))

    def test_missing_extra_and_wrong_fields_are_rejected(self):
        for key in self.issue:
            value = dict(self.issue)
            del value[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                canonical_admin_intent(value)
        for invalid in (None, [], "", {"action": "foo"}, dict(self.issue, node="gway-001"),
                        dict(self.issue, path="/etc/gway/secrets"),
                        dict(self.issue, bearer="gwr_abc"), dict(self.issue, operator_approved=True)):
            with self.subTest(invalid=str(invalid)[:70]), self.assertRaises(ValueError):
                canonical_admin_intent(invalid)

    def test_no_scope_escalation_or_downscoping(self):
        for scopes in ([], ["gway:read"], ["gway:execute"],
                       ["gway:read", "gway:read"],
                       ["gway:read", "gway:execute", "admin"],
                       "gway:read gway:execute", [None, "gway:execute"]):
            with self.subTest(scopes=scopes):
                self.rejects(scopes=scopes)

    def test_lifetime_is_bounded_and_booleans_not_integers(self):
        for lifetime in (True, False, 0, 59, MAX_LIFETIME_SECONDS + 1, 30.5, None, "3600"):
            with self.subTest(lifetime=lifetime):
                self.rejects(lifetime_seconds=lifetime)
        self.assertTrue(canonical_admin_intent(dict(self.issue, lifetime_seconds=60)))
        self.assertTrue(canonical_admin_intent(
            dict(self.issue, lifetime_seconds=MAX_LIFETIME_SECONDS)))

    def test_idempotency_is_exact_random_handle_shape(self):
        for request_id in ("", "A" * 32, "a" * 31, "a" * 33, "xyz", None, 1, True):
            with self.subTest(request_id=request_id):
                self.rejects(request_id=request_id)

    def test_revoke_has_separate_explicit_intent(self):
        revoke = {"action": "revoke_mcp_bearer", "key_id": "b" * 24,
                  "request_id": "a" * 32}
        self.assertTrue(canonical_admin_intent(revoke))
        for change in ({"key_id": "../../etc/passwd"}, {"key_id": "B" * 24},
                       {"lifetime_seconds": 900}, {"scopes": ["gway:read"]},
                       {"node": "gway-001"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                canonical_admin_intent(dict(revoke, **change))
        self.assertNotEqual(admin_intent_digest(revoke), admin_intent_digest(self.issue))

    def test_no_secret_broker_authority_prematurely(self):
        for action in ("reveal_secret", "update_secret", "enroll_passkey",
                       "issue_mcp_bearer_root", "node_exec"):
            with self.subTest(action=action), self.assertRaises(ValueError):
                canonical_admin_intent(dict(self.issue, action=action))


if __name__ == "__main__":
    unittest.main()
