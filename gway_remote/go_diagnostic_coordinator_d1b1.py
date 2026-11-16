"""Issue #561 D1-B1: PURE coordinator model, never an execution authority.

No clocks, I/O, SQLite, system calls, locks, subprocesses or production imports.
All witnesses are supplied by a hermetic test harness; their names do NOT
authenticate them. A passing decision is a model transition, not permission.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping

from .maintenance_fence_resources import ResourceError, plan, conflicts, ResourcePlan
from .maintenance_fence_provenance import (
    BootSample, ProvenanceError, validate_claimed_binding,
)

MAX_EVENTS = 4096
MAX_GENERATION = (1 << 63) - 1
GLOBAL_LOCK_ORDER = ("github_queue", "node_coordinator",
                     "sqlite_transaction", "legacy_flock", "side_effect")


class ModelError(ValueError):
    def __init__(self):
        super().__init__("invalid_offline_coordinator_d1b1")


class State(str, Enum):
    HELD = "held"
    UNCERTAIN = "uncertain"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class Witness:
    """Injected independently by test callers; NOT verified by this class."""

    principal: str
    node: str
    repo: str
    sha: str
    source: str
    request_id: str
    sample: BootSample
    resources: tuple[str, ...]


@dataclass(frozen=True)
class Reservation:
    binding_items: tuple[tuple[str, object], ...]
    resources: tuple[str, ...]
    generation: int
    state: State
    reason: str
    children_reaped: bool = False
    workspace_removed: bool = False

    def binding(self) -> dict:
        return dict(self.binding_items)


@dataclass(frozen=True)
class Snapshot:
    """Atomic *value* for test simulation; not a persisted journal."""

    records: tuple[Reservation, ...] = ()
    generation: int = 0
    events: int = 0


@dataclass(frozen=True)
class Receipt:
    state: State
    reason: str
    generation: int
    request_id: str

    def sanitized(self) -> dict[str, object]:
        return {"schema": "go-diagnostic-coordinator/d1b1-offline",
                "state": self.state.value, "reason": self.reason,
                "generation": self.generation, "request_id": self.request_id}


def _fail_if_invalid(snapshot: Snapshot) -> None:
    if type(snapshot) is not Snapshot or type(snapshot.records) is not tuple:
        raise ModelError()
    if (type(snapshot.generation) is not int or not 0 <= snapshot.generation <= MAX_GENERATION
            or type(snapshot.events) is not int or not 0 <= snapshot.events <= MAX_EVENTS):
        raise ModelError()
    ids = set()
    active = []
    for item in snapshot.records:
        if type(item) is not Reservation or type(item.state) is not State:
            raise ModelError()
        binding = item.binding()
        if (len(binding) != len(item.binding_items) or
                type(binding.get("request_id")) is not str or
                binding["request_id"] in ids or
                type(item.generation) is not int or
                not 0 < item.generation <= snapshot.generation):
            raise ModelError()
        ids.add(binding["request_id"])
        try:
            canonical = plan(item.resources)
            if canonical.resources != item.resources:
                raise ModelError()
            if item.state is not State.TERMINAL:
                if any(conflicts(canonical, other) for other in active):
                    raise ModelError()
                active.append(canonical)
        except ResourceError:
            raise ModelError() from None


def _binding_check(binding: Mapping, witness: Witness) -> tuple[tuple, tuple]:
    if type(binding) is not dict or type(witness) is not Witness:
        raise ModelError()
    if type(witness.resources) is not tuple:
        raise ModelError()
    try:
        resources = plan(witness.resources)
        if resources.resources != witness.resources:
            raise ModelError()
        validate_claimed_binding(
            binding, trusted_principal=witness.principal,
            trusted_node=witness.node, trusted_repo=witness.repo,
            trusted_sha=witness.sha, trusted_source=witness.source,
            trusted_request_id=witness.request_id,
            declared_resources=witness.resources,
            trusted_resources=witness.resources, trusted_sample=witness.sample)
    except (ResourceError, ProvenanceError):
        raise ModelError() from None
    return tuple(sorted(binding.items())), resources.resources


def _next(snapshot: Snapshot, item: Reservation, *, append: bool) -> Snapshot:
    if snapshot.events >= MAX_EVENTS:
        raise ModelError()
    items = snapshot.records + (item,) if append else tuple(
        item if old.binding()["request_id"] == item.binding()["request_id"] else old
        for old in snapshot.records)
    result = Snapshot(items, max(snapshot.generation, item.generation), snapshot.events + 1)
    _fail_if_invalid(result)
    return result


def reserve(snapshot: Snapshot, binding: dict, witness: Witness) -> tuple[Snapshot, Receipt]:
    """Pure all-or-nothing admission MODEL. No concurrency guarantee between calls."""
    _fail_if_invalid(snapshot)
    identity, resources = _binding_check(binding, witness)
    old = next((r for r in snapshot.records
                if r.binding()["request_id"] == witness.request_id), None)
    if old is not None:
        if old.binding_items != identity or old.resources != resources:
            raise ModelError()
        return snapshot, Receipt(old.state, "idempotent", old.generation, witness.request_id)
    if snapshot.generation >= MAX_GENERATION or snapshot.events >= MAX_EVENTS:
        raise ModelError()
    requested = ResourcePlan(resources)
    if any(conflicts(requested, ResourcePlan(r.resources))
           for r in snapshot.records if r.state is not State.TERMINAL):
        raise ModelError()
    item = Reservation(identity, resources, snapshot.generation + 1,
                       State.HELD, "reserved")
    result = _next(snapshot, item, append=True)
    return result, Receipt(State.HELD, "reserved", item.generation, witness.request_id)


def observe(snapshot: Snapshot, request_id: str, *, sample: BootSample) -> tuple[Snapshot, Receipt]:
    """Expiry/boot change cannot release resources, including on reboot."""
    _fail_if_invalid(snapshot)
    if type(sample) is not BootSample:
        raise ModelError()
    item = next((r for r in snapshot.records
                 if r.binding()["request_id"] == request_id), None)
    if item is None:
        raise ModelError()
    if item.state is not State.HELD:
        return snapshot, Receipt(item.state, item.reason, item.generation, request_id)
    binding = item.binding()
    reason = ("boot_changed" if binding["boot_id"] != sample.boot_id
              else "expired" if sample.now_ns >= binding["lease_until_ns"] else None)
    if reason is None:
        return snapshot, Receipt(State.HELD, "unchanged", item.generation, request_id)
    updated = replace(item, state=State.UNCERTAIN, reason=reason)
    result = _next(snapshot, updated, append=False)
    return result, Receipt(State.UNCERTAIN, reason, item.generation, request_id)


def finish(snapshot: Snapshot, request_id: str, *, generation: int,
           sample: BootSample, children_reaped: bool,
           workspace_removed: bool) -> tuple[Snapshot, Receipt]:
    """Conceptual clean completion, NOT a C1 journal transition or unlock."""
    _fail_if_invalid(snapshot)
    if type(sample) is not BootSample or type(generation) is not int:
        raise ModelError()
    item = next((r for r in snapshot.records
                 if r.binding()["request_id"] == request_id), None)
    if item is None or item.generation != generation:
        raise ModelError()
    if item.state is not State.HELD:
        raise ModelError()
    binding = item.binding()
    if (binding["boot_id"] != sample.boot_id
            or sample.now_ns >= binding["lease_until_ns"]
            or children_reaped is not True or workspace_removed is not True):
        reason = ("boot_changed" if binding["boot_id"] != sample.boot_id
                  else "expired" if sample.now_ns >= binding["lease_until_ns"]
                  else "children_or_cleanup_unknown")
        updated = replace(item, state=State.UNCERTAIN, reason=reason)
        result = _next(snapshot, updated, append=False)
        return result, Receipt(State.UNCERTAIN, reason, generation, request_id)
    updated = replace(item, state=State.TERMINAL, reason="clean_finished",
                      children_reaped=True, workspace_removed=True)
    result = _next(snapshot, updated, append=False)
    return result, Receipt(State.TERMINAL, "clean_finished", generation, request_id)


def recovery_preview(snapshot: Snapshot, request_id: str, *,
                     expected_generation: int, quiescence_attested: bool,
                     admin_attested: bool) -> str:
    """Offline consistency preview; cannot recover or release an actual lock."""
    _fail_if_invalid(snapshot)
    item = next((r for r in snapshot.records
                 if r.binding()["request_id"] == request_id), None)
    if (item is None or item.state is not State.UNCERTAIN
            or type(expected_generation) is not int
            or item.generation != expected_generation
            or quiescence_attested is not True or admin_attested is not True):
        raise ModelError()
    return "offline_recovery_preconditions_only"


def check_order(phases: tuple[str, ...]) -> tuple[str, ...]:
    if (type(phases) is not tuple or len(set(phases)) != len(phases)
            or any(type(p) is not str or p not in GLOBAL_LOCK_ORDER for p in phases)
            or phases != tuple(sorted(phases, key=GLOBAL_LOCK_ORDER.index))):
        raise ModelError()
    return phases
