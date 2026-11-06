"""Load identical, operator-provisioned MCP source policy on both hosts.

The policy file is an explicitly configured, root-owned, immutable-by-service
artifact. A missing file never enables a source. No network discovery or
caller-controlled configuration is accepted.
"""
import hashlib
import json
import os
from pathlib import Path

from .mcp_source_registry import SourceRegistration, compose_source_catalog

MAX_POLICY = 65536


def load_source_policy(path, *, expected_sha256, builtins=()):
    if type(path) is not str or not path.startswith("/etc/gway-mcp-gateway/"):
        raise ValueError("source policy must live in the protected configuration directory")
    if type(expected_sha256) is not str or len(expected_sha256) != 64 or any(
            ch not in "0123456789abcdef" for ch in expected_sha256):
        raise ValueError("source policy checksum required")
    file = Path(path)
    if file.is_symlink():
        raise ValueError("source policy symlink denied")
    stat = file.stat()
    if not file.is_file() or stat.st_uid != 0 or stat.st_mode & 0o022:
        raise ValueError("source policy must be root owned and non-writable by service")
    with file.open("rb") as stream:
        raw = stream.read(MAX_POLICY + 1)
    if len(raw) > MAX_POLICY or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("source policy digest mismatch")
    policy = json.loads(raw)
    if type(policy) is not dict or set(policy) != {"version", "sources"} or policy["version"] != 1:
        raise ValueError("invalid source policy")
    if type(policy["sources"]) is not list or len(policy["sources"]) > 16:
        raise ValueError("invalid source registry")
    registrations, approved = [], {}
    for item in policy["sources"]:
        if type(item) is not dict or set(item) != {"registration", "tools"}:
            raise ValueError("invalid source entry")
        data = item["registration"]
        if type(data) is not dict or set(data) != {
                "source_id", "revision", "executable", "argv", "run_as", "enabled", "permission"}:
            raise ValueError("invalid registration")
        registration = SourceRegistration(**{**data, "argv": tuple(data["argv"])})
        if registration.source_id in approved:
            raise ValueError("duplicate source")
        registrations.append(registration)
        if registration.enabled:
            approved[registration.source_id] = item["tools"]
        elif item["tools"]:
            raise ValueError("disabled source cannot advertise tools")
    compose_source_catalog(builtins, registrations, approved)
    return tuple(registrations), approved


def policy_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def classify_source_catalog(registration, discovered):
    """Classify all tools; never grant execution based on source metadata.

    Untrusted/missing annotations default to execute-required. The read-only
    catalog remains bounded by the independently approved source permission.
    """
    if not isinstance(registration, SourceRegistration) or not registration.enabled:
        raise ValueError("registered enabled source required")
    if type(discovered) is not list or len(discovered) > 64:
        raise ValueError("invalid discovered catalog")
    names = set()
    readonly, execute = [], []
    for tool in discovered:
        if type(tool) is not dict or type(tool.get("name")) is not str:
            raise ValueError("invalid discovered tool")
        name = tool["name"]
        if name in names:
            raise ValueError("duplicate discovered tool")
        names.add(name)
        annotations = tool.get("annotations")
        if type(annotations) is dict and annotations.get("readOnlyHint") is True and annotations.get("destructiveHint") is not True:
            readonly.append(tool)
        else:
            execute.append(tool)
    compose_source_catalog((), (registration,), {registration.source_id: readonly})
    return {
        "read": sorted(readonly, key=lambda tool: tool["name"]),
        "execute_required": sorted(execute, key=lambda tool: tool["name"]),
    }


def propose_readonly_catalog(registration, discovered):
    """Select all read tools; execute-required tools are classified but withheld."""
    return classify_source_catalog(registration, discovered)["read"]
