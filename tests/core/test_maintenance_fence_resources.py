"""Hermetic adversarial acceptance for resource-scoped MF V1-B."""
from dataclasses import FrozenInstanceError
import unittest

from gway_remote.maintenance_fence_resources import (
    ResourceError, ResourcePlan, acquire_order, conflicts, overlaps, plan,
)


class ResourcePlannerTests(unittest.TestCase):
    def test_equal_and_hierarchical_conflicts(self):
        a = "node/gway-001"
        b = "node/gway-001/deploy/ocpp-simulator"
        c = "node/gway-001/service/ocpp-csms"
        self.assertTrue(overlaps(a, b))
        self.assertTrue(overlaps(b, a))
        self.assertTrue(overlaps(b, b))
        self.assertFalse(overlaps(b, c))
        self.assertFalse(overlaps(a, "node/gway-002"))
        self.assertFalse(overlaps("node/gway-001", "node/gway-010"))

    def test_canonical_sorted_order_and_duplicate_idempotence(self):
        x = "node/gway-001/service/ocpp-csms"
        y = "node/gway-001/deploy/ocpp-simulator"
        self.assertEqual(plan([x, y, x]), plan([y, x]))
        self.assertEqual(acquire_order(plan([x, y])), tuple(sorted((x, y))))
        self.assertEqual(acquire_order(plan([x, y])), acquire_order(plan([y, x])))

    def test_node_wide_claim_subsumes_deploy_and_service(self):
        result = plan([
            "node/gway-001/deploy/ocpp-simulator",
            "node/gway-001",
            "node/gway-001/service/ocpp-csms",
        ])
        self.assertEqual(result.resources, ("node/gway-001",))

    def test_independent_resources_can_coexist(self):
        simulator = plan(["node/gway-001/deploy/ocpp-simulator"])
        reports = plan(["node/gway-001/deploy/ocpp-reports"])
        network = plan(["node/gway-001/network/nftables"])
        self.assertFalse(conflicts(simulator, reports))
        self.assertFalse(conflicts(simulator, network))
        self.assertTrue(conflicts(simulator, plan(["node/gway-001"])))
        self.assertTrue(conflicts(simulator, simulator))

    def test_explicit_shared_resource_detects_conflict(self):
        a = plan(["node/gway-001/deploy/ocpp-simulator",
                  "node/gway-001/network/nftables"])
        b = plan(["node/gway-001/service/ocpp-csms",
                  "node/gway-001/network/nftables"])
        self.assertTrue(conflicts(a, b))

    def test_malformed_untrusted_paths_fail_closed(self):
        invalid = [
            "", "node", "node//deploy/test", "node/gway-001/",
            "node/gway-001/deploy", "node/gway-001/deploy/",
            "node/gway-001/deploy/../secret",
            "node/gway-001/deploy/-bad", "node/gway-001/deploy/.bad",
            "node/gway-001/unknown/a", "node/gway-001/deploy/foo/bar",
            "node/GWAY-001", "node/gway-001\n",
            "node/gway-001/deploy/ocpp_simulator",
            "node/gway-001/deploy/" + "x" * 65,
            "node/gway-001/deploy/" + "x" * 300,
        ]
        for resource in invalid:
            with self.subTest(resource=repr(resource)), self.assertRaises(ResourceError):
                plan([resource])

    def test_bad_collection_and_size_rejected(self):
        for resources in ([], (), "", ["node/gway-001"] * 33,
                          {"node/gway-001": True}, None, [None]):
            with self.subTest(value=type(resources).__name__), self.assertRaises(ResourceError):
                plan(resources)
        with self.assertRaises(ResourceError):
            conflicts(plan(["node/gway-001"]), object())

    def test_direct_forged_unsorted_redundant_and_mutated_plan_rejected(self):
        a = "node/gway-001"
        b = "node/gway-001/deploy/ocpp-simulator"
        c = "node/gway-002"
        for malformed in ((b, a), (a, b), (a, a), (c, a), ()):
            with self.subTest(resources=malformed), self.assertRaises(ResourceError):
                ResourcePlan(malformed)
        with self.assertRaises(FrozenInstanceError):
            plan([a]).resources = (c,)

    def test_deterministic_two_node_lock_order(self):
        p = plan(["node/gway-002/service/ocpp-csms",
                  "node/gway-001/deploy/ocpp-simulator"])
        self.assertEqual(
            acquire_order(p),
            ("node/gway-001/deploy/ocpp-simulator",
             "node/gway-002/service/ocpp-csms"),
        )


if __name__ == "__main__":
    unittest.main()
