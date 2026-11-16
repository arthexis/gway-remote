"""Hermetic V1-D0 inventory tests; source checks are read-only."""
from dataclasses import replace
from pathlib import Path
import unittest

from gway_remote.maintenance_fence_effect_inventory import (
    EXPECTED_ROUTES, LOCK_ORDER, ROUTES, InventoryError,
    audit_local_source_anchors, possible_conflicts,
    validate_catalog, validate_lock_sequence,
)


class EffectInventoryTests(unittest.TestCase):
    def test_expected_routes_exact_and_unique(self):
        self.assertEqual(set(r.route_id for r in validate_catalog()), EXPECTED_ROUTES)
        self.assertEqual(len(ROUTES), len(EXPECTED_ROUTES))

    def test_effect_anchors_exist_in_repository_snapshot(self):
        root = Path(__file__).resolve().parents[2]
        paths = [r.source for r in ROUTES if r.visibility == "local_source"]
        self.assertEqual(len(paths), 8)
        def reader(rel):
            return (root / rel).read_text(encoding="utf-8")
        self.assertEqual(len(audit_local_source_anchors(ROUTES, reader)), 8)

    def test_missing_or_changed_anchor_fails_closed(self):
        fixture = {r.source: r.anchor for r in ROUTES if r.visibility == "local_source"}
        # Multiple anchors may be in same file; use source text union.
        fixture = {}
        for route in ROUTES:
            if route.visibility == "local_source":
                fixture[route.source] = fixture.get(route.source, "") + route.anchor + "\n"
        self.assertEqual(len(audit_local_source_anchors(ROUTES, fixture.__getitem__)), 8)
        fixture["gway_remote/node_exec_worker.py"] = ""
        with self.assertRaises(InventoryError):
            audit_local_source_anchors(ROUTES, fixture.__getitem__)

    def test_route_removal_mutation_and_duplicates_fail(self):
        first = ROUTES[0]
        bad = [
            ROUTES[:-1],
            ROUTES + (first,),
            (replace(first, route_id="hidden"),) + ROUTES[1:],
            (replace(first, source="../outside.yml"),) + ROUTES[1:],
            (replace(first, anchor=""),) + ROUTES[1:],
            (replace(first, resources=("node/gway-002",)),) + ROUTES[1:],
            (replace(first, resources=("node/gway-001/deploy/x", "node/gway-001")),) + ROUTES[1:],
        ]
        for i, rows in enumerate(bad):
            with self.subTest(case=i), self.assertRaises(InventoryError):
                validate_catalog(rows)

    def test_all_node_mutations_conflict_with_whole_node(self):
        root = next(r for r in ROUTES if r.route_id == "node_exec_worker")
        for other in ROUTES:
            self.assertTrue(possible_conflicts(root, other), other.route_id)
            self.assertTrue(possible_conflicts(other, root), other.route_id)

    def test_simulator_and_provider_are_disjoint_under_narrow_claims(self):
        sim = next(r for r in ROUTES if r.route_id == "simulator_schedule")
        provider = next(r for r in ROUTES if r.route_id == "provider_broker")
        self.assertFalse(possible_conflicts(sim, provider))
        # Not a safety assertion: a shared filesystem/network must be declared
        # before claiming production independence.

    def test_lock_order_acyclic_and_duplicate_rejected(self):
        self.assertEqual(validate_lock_sequence(LOCK_ORDER), LOCK_ORDER)
        self.assertEqual(validate_lock_sequence(("node_coordinator", "legacy_flock")),
                         ("node_coordinator", "legacy_flock"))
        for phases in (("legacy_flock", "sqlite_transaction"),
                       ("legacy_flock", "legacy_flock"),
                       ("ghost",), ("side_effect", "github_queue")):
            with self.subTest(phases=phases), self.assertRaises(InventoryError):
                validate_lock_sequence(phases)

    def test_external_agentops_is_explicit_unverified(self):
        route = next(r for r in ROUTES if r.route_id == "agentops_federated")
        self.assertEqual(route.visibility, "external_unverified")
        self.assertEqual(route.anchor, "")
        with self.assertRaises(InventoryError):
            validate_catalog(tuple(replace(r, visibility="local_source")
                                   if r.route_id == route.route_id else r for r in ROUTES))


if __name__ == "__main__":
    unittest.main()
