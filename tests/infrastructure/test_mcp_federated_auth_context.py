"""Hermetic R1 contract tests: no OAuth, SSH, process, RPC, or node execution."""
import copy
import hashlib
import unittest

from gway_remote.mcp_federated_auth_context import (
    AuthContextError, FIELDS, MAX_ARGUMENT_BYTES, VERSION,
    arguments_sha256, build_context, canonical_arguments, validate_context,
)

PRINCIPAL = "a" * 24
REQUEST_ID = "b" * 32
ARGS = {"z": [1, True, None], "a": {"é": "mañana", "n": 1.0}}
ROUTE = {"verified_principal": PRINCIPAL, "node": "gway-001",
         "provider": "odoo", "tool": "quotation_update", "request_id": REQUEST_ID,
         "arguments": ARGS}


class FederatedAuthContextV1Tests(unittest.TestCase):
    def context(self):
        return build_context(**ROUTE)

    def check(self, context, **overrides):
        return validate_context(context, **{**ROUTE, **overrides})

    def test_exact_v1_fields_and_binding(self):
        ctx = self.context()
        self.assertEqual(set(ctx), FIELDS)
        self.assertEqual(ctx["version"], VERSION)
        self.assertEqual(ctx["scope"], "execute")
        self.assertEqual(ctx["principal_id"], PRINCIPAL)
        self.assertEqual(ctx["request_id"], REQUEST_ID)
        self.assertEqual(self.check(ctx), ctx)
        self.assertIsNot(self.check(ctx), ctx)

    def test_canonical_json_key_order_utf8_and_sha(self):
        expected = '{"a":{"n":1.0,"é":"mañana"},"z":[1,true,null]}'.encode()
        self.assertEqual(canonical_arguments(ARGS), expected)
        self.assertEqual(arguments_sha256(ARGS), hashlib.sha256(expected).hexdigest())
        self.assertEqual(arguments_sha256({"a": {"n": 1.0, "é": "mañana"}, "z": [1, True, None]}),
                         arguments_sha256(ARGS))
        self.assertNotEqual(arguments_sha256({"n": 1}), arguments_sha256({"n": 1.0}))

    def test_versions_missing_and_extra_fields_fail_closed(self):
        original = self.context()
        for invalid in ({**original, "version": 2}, {**original, "version": True},
                        {**original, "version": "1"},
                        {**original, "untrusted": "yes"},
                        {k: v for k, v in original.items() if k != "principal_id"},
                        [original], None):
            with self.subTest(invalid=repr(invalid)[:120]), self.assertRaises(AuthContextError):
                self.check(invalid)

    def test_read_scope_or_scope_type_rejected(self):
        for scope in ("read", "gway:read", "gway:execute", "EXECUTE", None, 1, True):
            with self.subTest(scope=scope), self.assertRaises(AuthContextError):
                self.check({**self.context(), "scope": scope})

    def test_principal_replacement_even_valid_syntax_fails_when_verified_independently(self):
        with self.assertRaises(AuthContextError):
            self.check({**self.context(), "principal_id": "c" * 24})
        with self.assertRaises(AuthContextError):
            self.check(self.context(), verified_principal="c" * 24)
        with self.assertRaises(AuthContextError):
            build_context(**{**ROUTE, "verified_principal": "c" * 25})

    def test_wrong_route_and_replayed_request_fail(self):
        for field, value in (("node", "gway-002"), ("provider", "agentops"),
                             ("tool", "quotation_create"), ("request_id", "c" * 32)):
            with self.subTest(field=field), self.assertRaises(AuthContextError):
                self.check(self.context(), **{field: value})
            with self.subTest(tampered=field), self.assertRaises(AuthContextError):
                self.check({**self.context(), field: value})

    def test_arguments_are_bound_and_digest_cannot_be_forged_without_rehashing(self):
        with self.assertRaises(AuthContextError):
            self.check(self.context(), arguments={"a": 2})
        with self.assertRaises(AuthContextError):
            self.check({**self.context(), "arguments_sha256": "0" * 64})
        with self.assertRaises(AuthContextError):
            self.check({**self.context(), "arguments_sha256": "Z" * 64})
        # SHA-256 is a digest, NOT a MAC or independent origin proof.

    def test_invalid_binding_types_and_routes_fail_build(self):
        invalids = (("verified_principal", "x" * 24),
                    ("verified_principal", "A" * 24),
                    ("verified_principal", True),
                    ("node", "Gway-001"), ("node", "gway-001/../../"),
                    ("provider", "odoo-bad"), ("provider", "Odoo"),
                    ("tool", "quotation/update"), ("tool", "quotation update"),
                    ("request_id", "b" * 31), ("request_id", "B" * 32))
        for field, value in invalids:
            with self.subTest(field=field, value=value), self.assertRaises(AuthContextError):
                build_context(**{**ROUTE, field: value})

    def test_invalid_argument_shapes_are_rejected(self):
        cycle = []
        cycle.append(cycle)
        nested = []
        cur = nested
        for _ in range(26):
            nxt = []
            cur.append(nxt)
            cur = nxt
        cases = ([], None, {1: "key"}, {"nan": float("nan")},
                 {"inf": float("inf")}, {"int": 2 ** 53},
                 {"tuple": (1, 2)}, {"obj": object()},
                 {"cycle": cycle}, {"nested": nested},
                 {"over": "x" * (MAX_ARGUMENT_BYTES + 1)},
                 {"bad_utf8": "\ud800"})
        for args in cases:
            with self.subTest(case=repr(args)[:100]), self.assertRaises(AuthContextError):
                build_context(**{**ROUTE, "arguments": args})

    def test_bound_to_original_arguments_without_mutating_inputs(self):
        before = copy.deepcopy(ARGS)
        ctx = self.context()
        self.assertEqual(before, ARGS)
        self.assertEqual(self.check(ctx), ctx)
        changed = copy.deepcopy(ARGS)
        changed["z"].append(False)
        with self.assertRaises(AuthContextError):
            self.check(ctx, arguments=changed)


if __name__ == "__main__":
    unittest.main()
