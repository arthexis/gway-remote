"""Explicit Agent Ops issue scope, independent of appliance deployment targets.

Adding a repository here does not enable its deployment or grant issue execution
authorization. Agent Ops enforces author, issue, label, and admission policy.
"""
from .target_export import export_targets

EXTRA_AGENT_ISSUE_REPOSITORIES = frozenset({"arthexis/gway-bastion"})


def allowed_issue_repositories() -> tuple[str, ...]:
    deployed = {row["repository"] for row in export_targets()["targets"]}
    return tuple(sorted(deployed | EXTRA_AGENT_ISSUE_REPOSITORIES))
