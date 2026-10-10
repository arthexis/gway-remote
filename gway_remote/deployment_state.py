"""Deployment history inspection and conservative bootstrap planning.

No write operations. Bootstrap must be performed only after checking the
installed artifact on gway-001 against a specific repository revision.
"""
from __future__ import annotations

from dataclasses import dataclass

from .reconcile import TARGETS


@dataclass(frozen=True)
class BootstrapCandidate:
    name: str
    repository: str
    installed_sha: str | None
    status: str
    reason: str


def bootstrap_audit(states):
    """Describe missing deployment records; never infer installation from main.

    A successful previous *workflow* is not evidence of the installed SHA.
    """
    by_name = {state.name: state for state in states}
    result = []
    for name, repository in TARGETS:
        state = by_name.get(name)
        if state is None:
            result.append(BootstrapCandidate(name, repository, None, "blocked", "target state missing"))
        elif state.deployed_sha is None:
            result.append(BootstrapCandidate(
                name, repository, None, "verification-required",
                "inspect installed revision and runtime health on gway-001 before creating a successful deployment record",
            ))
        else:
            result.append(BootstrapCandidate(
                name, repository, state.deployed_sha, "recorded",
                "GitHub deployment history has a successful revision; runtime verification is separate",
            ))
    return tuple(result)
