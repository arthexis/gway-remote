import unittest

from gway_remote.reconcile import TARGETS
from gway_remote.target_export import export_targets


class TestTargetExport(unittest.TestCase):
    def test_export_matches_canonical_targets(self):
        snapshot = export_targets()
        self.assertEqual(snapshot["schema"], 1)
        self.assertEqual(len(snapshot["revision"]), 40)
        self.assertEqual(
            [(row["name"], row["repository"]) for row in snapshot["targets"]],
            list(TARGETS),
        )
        self.assertEqual(snapshot, export_targets())
