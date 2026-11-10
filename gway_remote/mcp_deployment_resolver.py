"""Resolve deployment eligibility exclusively from node-owned installed providers.

This read-only resolver does not dispatch or grant execute permission.
"""
import re

from .mcp_installed_providers import discover_installed_providers

_APP = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def resolve_deployment(application, *, discover=discover_installed_providers):
    if type(application) is not str or not _APP.fullmatch(application):
        raise ValueError("invalid deployment application")
    matches = [source for source in discover() if source.source_id == application]
    if len(matches) != 1 or not matches[0].enabled or matches[0].deployment is None:
        raise PermissionError("provider has no authorized deployment declaration")
    from .mcp_deployment_contract import validate_deployment
    return validate_deployment(matches[0].deployment)
