from gway_remote.reconcile import TARGETS
from gway_remote.target_export import export_targets


def test_export_matches_canonical_targets():
    snapshot = export_targets()
    assert snapshot["schema"] == 1
    assert len(snapshot["revision"]) == 40
    assert [(x["name"], x["repository"]) for x in snapshot["targets"]] == list(TARGETS)
    assert snapshot == export_targets()
