"""Read-only, versioned export of the canonical Remote deployment target set."""
import hashlib
import json

from .catalog_shadow import check_shadow_parity, load_catalog_data


def export_targets():
    # P3-A reads the P1 resource, but registry parity remains mandatory.
    # No fallback to reconcile.TARGETS on missing or drifting metadata.
    catalog = check_shadow_parity(load_catalog_data())
    targets = [{"name": target.id, "repository": target.repository}
               for target in catalog.targets]
    if len({row["name"] for row in targets}) != len(targets):
        raise ValueError("duplicate deployment target")
    if len({row["repository"] for row in targets}) != len(targets):
        raise ValueError("duplicate repository")
    canonical = json.dumps(targets, sort_keys=True, separators=(",", ":")).encode()
    revision = hashlib.sha1(canonical).hexdigest()
    return {"schema": 1, "revision": revision, "targets": targets}
