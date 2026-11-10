"""Pinned registration and validated MCP tool catalog composition.

This module does not launch processes, load configuration, or change live tool
discovery. Only an operator-provisioned, release-pinned registry may use it.
"""
from dataclasses import dataclass
import re
from pathlib import PurePosixPath

from .mcp_catalog import ToolCatalogError, compose_catalog

_NAME = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_TOOL = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class SourceRegistration:
    source_id: str
    revision: str
    executable: str
    argv: tuple[str, ...]
    run_as: str
    enabled: bool = False
    deployment: object = None

    def __post_init__(self):
        if not isinstance(self.source_id, str) or not _NAME.fullmatch(self.source_id):
            raise ValueError("invalid source id")
        if not isinstance(self.revision, str) or not _SHA.fullmatch(self.revision):
            raise ValueError("source revision must be pinned to a full SHA")
        if not isinstance(self.executable, str) or not self.executable.startswith("/"):
            raise ValueError("source executable must be absolute")
        path = PurePosixPath(self.executable)
        if ".." in self.executable.split("/") or str(path) != self.executable or self.executable == "/":
            raise ValueError("unsafe executable path")
        if type(self.argv) is not tuple or not self.argv or any(
            type(arg) is not str or not arg or "\x00" in arg for arg in self.argv
        ) or self.argv[0] != self.executable:
            raise ValueError("invalid fixed argv")
        if not isinstance(self.run_as, str) or not _NAME.fullmatch(self.run_as):
            raise ValueError("invalid service identity")
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if self.deployment is not None:
            from .mcp_deployment_contract import validate_deployment
            validate_deployment(self.deployment)


def compose_source_catalog(builtin_tools, registrations, source_tools):
    """Compose registered source declarations, rejecting collisions.

    This function validates discovery, not caller authorization.
    """
    if type(registrations) not in (tuple, list) or type(source_tools) is not dict:
        raise ToolCatalogError("invalid source registry")
    known = set()
    catalogs = [builtin_tools]
    for registration in registrations:
        if not isinstance(registration, SourceRegistration):
            raise ToolCatalogError("untrusted source registration")
        if registration.source_id in known:
            raise ToolCatalogError("duplicate source id")
        known.add(registration.source_id)
        if not registration.enabled:
            if registration.source_id in source_tools:
                raise ToolCatalogError("disabled source advertised tools")
            continue
        declared = source_tools.get(registration.source_id)
        if type(declared) not in (tuple, list):
            raise ToolCatalogError("missing approved source catalog")
        mapped = []
        for tool in declared:
            if type(tool) is not dict or not isinstance(tool.get("name"), str):
                raise ToolCatalogError("malformed source tool")
            name = tool["name"]
            if not _TOOL.fullmatch(name) or name.startswith("_"):
                raise ToolCatalogError("invalid source tool name")
            mapped.append({**tool, "name": registration.source_id + "__" + name})
        catalogs.append(mapped)
    if set(source_tools) - known:
        raise ToolCatalogError("unregistered source catalog")
    return compose_catalog(*catalogs)
