"""Non-invasive Bastion staging/activation evidence consumer."""
import json
import os
import re
from pathlib import Path

_SHA = re.compile(r"[0-9a-f]{40}")


def read_bastion_evidence(root=None):
    root = Path(root) if root is not None else Path(os.environ.get("BASTION_INSTALL_ROOT", "/opt/gway-bastion"))
    revisions = {}
    try:
        for kind in ("staged", "activated"):
            file = root / "deployment" / (kind + ".json")
            if not file.exists() and not file.is_symlink():
                revisions[kind] = None
                continue
            if file.is_symlink() or not file.is_file():
                raise ValueError("invalid evidence file")
            payload = json.loads(file.read_text(encoding="utf-8"))
            if (not isinstance(payload, dict) or set(payload) != {"schema", "revision"}
                    or payload["schema"] != 1 or not isinstance(payload["revision"], str)
                    or not _SHA.fullmatch(payload["revision"])):
                raise ValueError("invalid evidence schema")
            sha = payload["revision"]
            revision_file = root / "releases" / sha / "REVISION"
            if revision_file.is_symlink() or not revision_file.is_file() or revision_file.read_text().strip() != sha:
                raise ValueError("unverified revision")
            revisions[kind] = sha
    except (OSError, ValueError, UnicodeError, TypeError):
        return {"release_state": "unknown", "staged_sha": None, "activated_sha": None,
                "runtime": "unknown", "evidence": "invalid"}
    activated = revisions["activated"]
    staged = revisions["staged"]
    return {"release_state": "activated" if activated else "staged" if staged else "unknown",
            "staged_sha": staged, "activated_sha": activated,
            "runtime": "unknown" if activated or not staged else "not_applicable",
            "evidence": "verified" if activated or staged else "missing"}
