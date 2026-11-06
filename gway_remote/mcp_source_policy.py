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


def propose_readonly_catalog(registration, discovered):
    """Discover every read-only tool of a trusted, pinned source.

    The operator approves the source and its read permission ceiling, not
    individual names. This proposal is not authority to execute: runtime
    dispatch must revalidate the source, version, and read-only contract.
    """
    if not isinstance(registration, SourceRegistration) or not registration.enabled or registration.permission != "read":
        raise ValueError("read-only registered source required")
    if type(discovered) is not list or len(discovered) > 64:
        raise ValueError("invalid discovered catalog")
    selected = []
    for tool in discovered:
        if type(tool) is not dict or type(tool.get("name")) is not str:
            raise ValueError("invalid discovered tool")
        annotations = tool.get("annotations")
        if type(annotations) is not dict:
            raise ValueError("missing tool annotations")
        if annotations.get("readOnlyHint") is True and annotations.get("destructiveHint") is not True:
            selected.append(tool)
    compose_source_catalog((), (registration,), {registration.source_id: selected})
    return sorted(selected, key=lambda tool: tool["name"])
