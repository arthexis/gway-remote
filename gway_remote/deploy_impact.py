"""Conservative push impact gate for GWay Remote's existing auto-deploy.

Only exact, reviewed, currently non-runtime V1 evidence files are safe.
Everything else requires the existing gway-001 and Watchtower deployment path.
Unverifiable history raises and blocks both jobs rather than silently skipping.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

_SHA = re.compile(r"[0-9a-f]{40}\Z")
SAFE_PATHS = frozenset({
    "docs/development-evidence-v1.md",
    "tests/deployment/test_development_evidence.py",
    "gway_remote/development_evidence.py",
})


def classify_paths(paths):
    """Return skip only for a non-empty, exact subset of reviewed V1 paths."""
    if not isinstance(paths, (tuple, list)) or not paths:
        raise ValueError("missing changed-file evidence")
    if any(not isinstance(path, str) or not path or
           path.startswith("/") or "\x00" in path for path in paths):
        raise ValueError("invalid changed-file evidence")
    return "skip" if all(path in SAFE_PATHS for path in paths) else "deploy"


def classify_push(before, after, *, runner=subprocess.run):
    """Compare full before/after commits; reject missing/rewritten histories.

    All git commands operate on the checked-out local repository. The full
    push range, not a paginated PR file list, is the unit of impact.
    """
    if not all(isinstance(s, str) and _SHA.fullmatch(s) and s != "0" * 40
               for s in (before, after)) or before == after:
        raise ValueError("invalid push revisions")
    def git(*args):
        return runner(["git", *args], capture_output=True, check=True)
    git("cat-file", "-e", before + "^{commit}")
    git("cat-file", "-e", after + "^{commit}")
    git("merge-base", "--is-ancestor", before, after)
    data = git("diff", "--no-ext-diff", "--no-renames", "--name-only",
               "-z", before, after, "--").stdout
    if not isinstance(data, bytes) or not data.endswith(b"\x00"):
        raise ValueError("empty or malformed push diff")
    try:
        paths = tuple(path.decode("utf-8") for path in data[:-1].split(b"\x00"))
    except UnicodeDecodeError as exc:
        raise ValueError("non-UTF8 diff path") from exc
    return classify_paths(paths)


def main():
    # Exceptions intentionally fail admission; deploy jobs require successful
    # admission. Never convert errors into a silent skip.
    decision = classify_push(os.environ["PUSH_BEFORE"], os.environ["PUSH_SHA"])
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as f:
        f.write("deploy=" + ("true" if decision == "deploy" else "false") + "\n")
    print("Deployment impact:", decision)


if __name__ == "__main__":
    main()
