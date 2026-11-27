"""Conservative push impact gate for GWay Remote's existing auto-deploy.

Only exact, reviewed, non-runtime evidence and Android delivery tooling are safe.
Everything else requires the existing gway-001 and Watchtower deployment path.
Unverifiable history raises and blocks both jobs rather than silently skipping.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

_SHA = re.compile(r"[0-9a-f]{40}\Z")
EVIDENCE_PATHS = frozenset({
    "docs/development-evidence-v1.md",
    "tests/deployment/test_development_evidence.py",
    "gway_remote/development_evidence.py",
})
# These are trusted workflow entrypoints/helpers/tests, not the running
# Mobile API, MCP provider, Watchtower, deploy scripts or configuration.
ANDROID_DELIVERY_PATHS = frozenset({
    ".github/workflows/android-canary-certificate.yml",
    ".github/workflows/android-canary-install.yml",
    ".github/workflows/android-canary.yml",
    ".github/workflows/android-release-candidate-sign.yml",
    ".github/workflows/android-release-candidate-install.yml",
    ".github/workflows/android-release-candidate.yml",
    "docs/android-single-release-candidate.md",
    "gway_remote/android_canary_certificate.py",
    "gway_remote/android_release_candidate.py",
    "gway_remote/android_rc_health.py",
    "gway_remote/android_release_gate.py",
    "tests/infrastructure/test_android_canary_certificate.py",
    "tests/infrastructure/test_android_canary_install_workflow.py",
    "tests/infrastructure/test_android_canary_workflow.py",
    "tests/infrastructure/test_android_release_candidate.py",
    "tests/infrastructure/test_android_rc_health.py",
    "tests/mobile/test_android_release_gate.py",
})
SAFE_PATHS = EVIDENCE_PATHS | ANDROID_DELIVERY_PATHS
# The classifier runs from the reviewed checkout in the hosted admission job.
# Updating its policy requires accompanying regression tests. It is not a
# runtime backend change. A policy-only change without tests remains deploy.
POLICY_PATHS = frozenset({
    "gway_remote/deploy_impact.py",
    "tests/deployment/test_deploy_impact.py",
})


def classify_paths(paths):
    """Skip only explicitly reviewed non-runtime paths, never a directory prefix."""
    if not isinstance(paths, (tuple, list)) or not paths:
        raise ValueError("missing changed-file evidence")
    if any(not isinstance(path, str) or not path or
           path.startswith("/") or "\x00" in path for path in paths):
        raise ValueError("invalid changed-file evidence")
    changed = frozenset(paths)
    if changed & POLICY_PATHS:
        return "skip" if POLICY_PATHS <= changed <= (SAFE_PATHS | POLICY_PATHS) else "deploy"
    return "skip" if changed <= SAFE_PATHS else "deploy"


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
