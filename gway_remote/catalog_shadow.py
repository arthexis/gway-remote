"""Strict P1/P3-A appliance metadata catalog: never deployment authority.

The public target export reads only the pure data loader, then separately checks
parity against reviewed registries. Installed root-owned inventory, handlers
and node-owned MCP manifests remain independent authorization boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import json
import re

SCHEMA = "gway-remote/appliance-catalog/v1"
RESOURCE = "appliance-targets.v1.json"
MAX_BYTES = 32768
MAX_TARGETS = 32
_TOP_KEYS = frozenset(("schema", "targets"))
_TARGET_KEYS = frozenset(("id", "repository", "adapter_id", "probe_id", "release_mode"))
_RESERVED = frozenset(("all", "admission", "report", "deploy"))
_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_ADAPTER = re.compile(r"deploy_[a-z0-9]+(?:_[a-z0-9]+)*\Z")
_MODES = frozenset(("standard", "stage_only"))


@dataclass(frozen=True)
class Target:
    id: str
    repository: str
    adapter_id: str
    probe_id: str | None
    release_mode: str


@dataclass(frozen=True)
class Catalog:
    schema: str
    targets: tuple[Target, ...]


def _unique_pairs(pairs):
    """Reject duplicate JSON properties, including in nested objects."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate catalog JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"non-JSON numeric constant: {value}")


def parse_catalog(source: str) -> Catalog:
    """Parse closed, bounded metadata without looking up hosts or executables.

    Validation is syntactic here; check_shadow_parity additionally binds every
    adapter/probe ID to an existing reviewed registry before accepting a catalog.
    """
    if type(source) is not str or len(source.encode("utf-8")) > MAX_BYTES:
        raise ValueError("invalid or oversized catalog text")
    try:
        data = json.loads(source, object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise ValueError("invalid catalog JSON") from exc
    if type(data) is not dict or set(data) != _TOP_KEYS or data["schema"] != SCHEMA:
        raise ValueError("unknown or malformed catalog schema")
    rows = data["targets"]
    if type(rows) is not list or not 0 < len(rows) <= MAX_TARGETS:
        raise ValueError("invalid catalog target list")
    targets = []
    ids, repos, jobs = set(), set(), set()
    for row in rows:
        if type(row) is not dict or set(row) != _TARGET_KEYS:
            raise ValueError("unknown or missing target field")
        name = row["id"]
        repo = row["repository"]
        adapter = row["adapter_id"]
        probe = row["probe_id"]
        mode = row["release_mode"]
        if type(name) is not str or not _ID.fullmatch(name) or name in _RESERVED:
            raise ValueError("invalid or reserved target id")
        job = name.replace("-", "_")
        if job in jobs or job in _RESERVED or name in ids:
            raise ValueError("duplicate or reserved derived job id")
        if type(repo) is not str or repo != f"arthexis/{name}":
            raise ValueError("invalid catalog repository")
        if repo in repos:
            raise ValueError("duplicate catalog repository")
        if type(adapter) is not str or not _ADAPTER.fullmatch(adapter):
            raise ValueError("invalid catalog adapter id")
        if probe is not None and (type(probe) is not str or not _ID.fullmatch(probe)):
            raise ValueError("invalid catalog probe id")
        if type(mode) is not str or mode not in _MODES:
            raise ValueError("invalid catalog release mode")
        # Staging is neither activation nor a health certificate.
        if (name == "gway-bastion") != (mode == "stage_only"):
            raise ValueError("Bastion must remain stage_only")
        if (name == "gway-bastion") != (probe is None):
            raise ValueError("only Bastion may lack a registered probe")
        ids.add(name)
        repos.add(repo)
        jobs.add(job)
        targets.append(Target(name, repo, adapter, probe, mode))
    return Catalog(SCHEMA, tuple(targets))


def check_shadow_parity(catalog: Catalog) -> Catalog:
    """Fail on any drift from the current seven known, reviewed targets.

    This is *not* a deploy admission or a probe execution; it reads Python
    registry objects and checks callable adapter existence without calling it.
    """
    from .reconcile import TARGETS
    from .best_effort import INSTALLERS
    from .probe_registry import PROBES
    from . import __main__ as reviewed_handlers

    if type(catalog) is not Catalog or catalog.schema != SCHEMA:
        raise ValueError("unexpected shadow catalog object")
    rows = catalog.targets
    if tuple((t.id, t.repository) for t in rows) != TARGETS:
        raise ValueError("catalog drifts from ordered reconcile.TARGETS")
    if tuple(INSTALLERS) != tuple(t.id for t in rows):
        raise ValueError("catalog drifts from reviewed installer registry")
    for target in rows:
        if INSTALLERS[target.id] != target.adapter_id:
            raise ValueError(f"catalog adapter mismatch: {target.id}")
        if not callable(getattr(reviewed_handlers, target.adapter_id, None)):
            raise ValueError(f"catalog adapter is not reviewed callable: {target.id}")
        expected_probe = target.id if target.id in PROBES else None
        if target.probe_id != expected_probe:
            raise ValueError(f"catalog probe mismatch: {target.id}")
        if target.probe_id is not None and PROBES[target.probe_id].kind == "unknown":
            raise ValueError(f"catalog probe has unknown kind: {target.id}")
    if set(PROBES) != {t.probe_id for t in rows if t.probe_id is not None}:
        raise ValueError("unexpected probe registry coverage")
    return catalog


def load_catalog_data() -> Catalog:
    """Read strictly validated descriptive JSON, without importing registries.

    This pure stage is NOT a deployment authorization or a verification of
    adapter/probe implementations. Keep the fixed packaged resource path and
    reject missing or malformed data, including for zipapp deployments.
    """
    try:
        resource = resources.files("gway_remote").joinpath("data", RESOURCE)
        content = resource.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("appliance catalog resource unavailable") from exc
    return parse_catalog(content)


def load_catalog() -> Catalog:
    """Preserve P1/P2's checked loader and all existing parity guarantees.

    Registry imports occur only inside check_shadow_parity, never in the pure
    data loader or at module import time.
    """
    return check_shadow_parity(load_catalog_data())
