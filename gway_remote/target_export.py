"""Read-only, versioned export of the canonical Remote deployment target set."""
import hashlib
import json

from .reconcile import TARGETS


def export_targets():
    targets = [{"name": name, "repository": repository} for name, repository in TARGETS]
    if len({row["name"] for row in targets}) != len(targets):
        raise ValueError("duplicate deployment target")
    if len({row["repository"] for row in targets}) != len(targets):
        raise ValueError("duplicate repository")
    canonical = json.dumps(targets, sort_keys=True, separators=(",", ":")).encode()
    revision = hashlib.sha1(canonical).hexdigest()
    return {"schema": 1, "revision": revision, "targets": targets}
