"""Read-only node-owned MCP provider diagnosis (#549 B).

The root-owned installed provider registry remains the *only* authority for
registration and executable arguments. The optional Watchtower catalog is an
untrusted, sanitized snapshot supplied by the operator, not OAuth access.
No shell, SSH, installation, token, filesystem write or deployment is done.
"""
import json
import os
import re
import socket
import stat
from pathlib import Path

from .mcp_installed_providers import INSTALL_DIR, discover_installed_providers
from .mcp_node_providers import provider_list
from .mcp_tool_scope import required_scope

_SOURCE_ID = re.compile(r"[a-z][a-z0-9_]{1,39}\Z")
_MAX_CATALOG = 262144
_MAX_TOOLS = 4096
_RECEIPT_STATES = frozenset({"never_run", "running", "succeeded", "failed"})


def load_watchtower_catalog(path):
    """Read a bounded regular JSON snapshot, never an arbitrary device or symlink.

    It must contain the sanitized data from the existing read-only
    mcp_catalog_inspect tool, not a bearer or full MCP argument payload.
    """
    file = Path(path)
    # Open without following symlinks; fstat the actual descriptor to avoid
    # a check/open race. O_NONBLOCK prevents a swapped FIFO from hanging.
    try:
        fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise ValueError("invalid_catalog_file") from exc
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode) or not 0 < meta.st_size <= _MAX_CATALOG:
            raise ValueError("invalid_catalog_file")
        raw = stream.read(_MAX_CATALOG + 1)
    if len(raw) > _MAX_CATALOG:
        raise ValueError("oversized_catalog_file")
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("invalid_catalog_json") from exc
    if (type(value) is not dict or type(value.get("schema")) is not int or value["schema"] != 1
            or type(value.get("count")) is not int
            or type(value.get("tools")) is not list
            or len(value["tools"]) > _MAX_TOOLS
            or value.get("count") != len(value["tools"])):
        raise ValueError("invalid_catalog_schema")
    for tool in value["tools"]:
        if (type(tool) is not dict
                or type(tool.get("name")) is not str
                or type(tool.get("node")) not in (str, type(None))
                or type(tool.get("source")) not in (str, type(None))
                or tool.get("required_scope") not in ("gway:read", "gway:execute")):
            raise ValueError("invalid_catalog_schema")
    return value


def _watchtower_compare(snapshot, source_id, node, advertised):
    """Compare names and scopes; *never* claim a caller's file is live proof."""
    if snapshot is None:
        return {"state": "unknown", "evidence": "not_supplied"}
    expected = {source_id + "__" + tool["name"]: "gway:" + required_scope(tool)
                for tool in advertised}
    observed = {}
    for row in snapshot["tools"]:
        if row["source"] != source_id:
            continue
        if row["node"] != node or row["name"] in observed:
            return {"state": "differs_snapshot", "evidence": "caller_supplied_unverified"}
        observed[row["name"]] = row["required_scope"]
    return {"state": "matches_snapshot" if expected == observed else "differs_snapshot",
            "evidence": "caller_supplied_unverified", "expected_count": len(expected),
            "observed_count": len(observed)}


def check_provider(source_id, *, directory=INSTALL_DIR, node=None, watchtower_catalog=None,
                   discover=discover_installed_providers, list_providers=provider_list,
                   receipt_reader=None):
    """Summarize a local manifest, advertised tools, and historical receipt.

    Installed SHA stays unknown: a provider manifest and a historical deployment
    receipt do *not* prove a release is active. A caller-supplied Watchtower
    snapshot cannot upgrade that evidence.
    """
    if type(source_id) is not str or not _SOURCE_ID.fullmatch(source_id):
        raise ValueError("invalid_source_id")
    node = socket.gethostname() if node is None else node
    if type(node) is not str or not node:
        raise ValueError("invalid_node")
    report = {
        "schema": 1, "source_id": source_id, "node": node,
        "state": "unavailable", "code": None,
        "manifest": {"state": "unknown"},
        "executable": {"state": "unknown"},
        "catalog": {"state": "unknown", "tools": []},
        "watchtower": {"state": "unknown", "evidence": "not_supplied"},
        "deployment": {"state": "unknown"},
        "receipt": {"state": "unknown", "evidence": "historical_only"},
        "installed_release": {"sha": None, "state": "unverified"},
    }
    try:
        registrations = discover(directory)
    except (OSError, ValueError, TypeError, KeyError):
        report["code"] = "registry_invalid_or_unreadable"
        report["manifest"] = {"state": "invalid_or_unreadable"}
        return report
    matches = [reg for reg in registrations if reg.source_id == source_id and reg.enabled]
    if len(matches) != 1:
        report["code"] = "provider_not_installed"
        report["manifest"] = {"state": "not_installed"}
        return report
    registration = matches[0]
    report["manifest"] = {"state": "valid", "revision": registration.revision}
    report["executable"] = {"state": "validated_by_manifest_parser"}
    if registration.deployment is None:
        report["deployment"] = {"state": "not_declared"}
        report["receipt"] = {"state": "not_applicable"}
    else:
        report["deployment"] = {"state": "declared",
                                "target_revision": registration.deployment["revision"]}
        if receipt_reader is None:
            from .mcp_deployment_broker import status as receipt_reader
        try:
            from .mcp_deployment_contract import validate_deployment
            receipt = receipt_reader(source_id, resolve=lambda _: validate_deployment(
                registration.deployment))
            state = receipt.get("state") if type(receipt) is dict else None
            if state not in _RECEIPT_STATES:
                raise ValueError("unexpected_receipt_state")
            report["receipt"] = {"state": state, "evidence": "historical_only"}
        except (OSError, ValueError, PermissionError, KeyError, TypeError):
            report["receipt"] = {"state": "unknown", "evidence": "historical_only"}
    # tools/list is the only provider invocation here. Never dispatch a tool.
    try:
        output = list_providers((registration,), node_id=node)
        entries = output["providers"]
        if type(entries) is not list or len(entries) != 1:
            raise ValueError("invalid_provider_catalog")
        entry = entries[0]
        if (entry.get("provider") != source_id or entry.get("status") != "available"
                or type(entry.get("tools")) is not list):
            report["code"] = "provider_discovery_unavailable"
            report["catalog"] = {"state": "unavailable", "tools": []}
            return report
        advertised = entry["tools"]
        tools = [{"name": tool["name"], "required_scope": "gway:" + required_scope(tool)}
                 for tool in advertised]
        report["catalog"] = {"state": "available", "tools": tools}
        report["watchtower"] = _watchtower_compare(
            watchtower_catalog, source_id, node, advertised)
        report["state"] = "available"
        if report["watchtower"]["state"] == "differs_snapshot":
            report["code"] = "catalog_snapshot_mismatch"
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, TimeoutError):
        report["code"] = "provider_discovery_unavailable"
        report["catalog"] = {"state": "unavailable", "tools": []}
    return report


def format_provider_check(report):
    lines = [f"MCP provider: {report['source_id']} on {report['node']}",
             f"Provider: {report['state']}",
             f"Manifest: {report['manifest']['state']}",
             f"Executable: {report['executable']['state']}",
             f"Catalog: {report['catalog']['state']} ({len(report['catalog']['tools'])} tools)",
             f"Watchtower: {report['watchtower']['state']} ({report['watchtower']['evidence']})",
             f"Deployment: {report['deployment']['state']}",
             f"Receipt: {report['receipt']['state']} (historical, not installed proof)",
             "Installed release SHA: unverified"]
    if report["code"]:
        lines.append("Diagnostic code: " + report["code"])
    return "\n".join(lines)
