"""Offline-only Go ARM64 diagnostic contract for #561.

Pure data validation: does not spawn, lock, inspect, authorize or access a node.
A validated plan/receipt is NOT a runtime permit or proof of isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
import re

from .maintenance_fence_resources import ResourceError, plan, conflicts

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_RECEIPT_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_ALLOWED_RESULTS = frozenset({"passed", "failed", "not_run"})
_STEPS = ("mod_tidy", "mod_verify", "build_backend", "build_uidlab")
_RESOURCES = ("node/gway-001",)  # Conservative whole-node footprint; V1-B canonical.
_ALLOWED_CODES = frozenset({
    "ok", "admission_denied", "busy", "timeout", "resource_limit",
    "dependency_unavailable", "sandbox_unavailable", "step_failed",
    "cleanup_unverified", "uncertain",
})


class ContractError(ValueError):
    """Only a stable code may be surfaced; no untrusted input is echoed."""


class Phase(str, Enum):
    PLANNED = "planned"
    ADMITTED = "admitted"
    RUNNING = "running"
    CLEANING = "cleaning"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


_ALLOWED_TRANSITIONS = {
    Phase.PLANNED: frozenset({Phase.ADMITTED, Phase.FAILED}),
    Phase.ADMITTED: frozenset({Phase.RUNNING, Phase.FAILED, Phase.UNCERTAIN}),
    Phase.RUNNING: frozenset({Phase.CLEANING, Phase.UNCERTAIN}),
    Phase.CLEANING: frozenset({Phase.SUCCEEDED, Phase.FAILED, Phase.UNCERTAIN}),
    Phase.SUCCEEDED: frozenset(),
    Phase.FAILED: frozenset(),
    Phase.UNCERTAIN: frozenset(),
}


def transition(current: Phase, next_phase: Phase) -> Phase:
    if not isinstance(current, Phase) or not isinstance(next_phase, Phase):
        raise ContractError("invalid_phase")
    if next_phase not in _ALLOWED_TRANSITIONS[current]:
        raise ContractError("invalid_transition")
    return next_phase


@dataclass(frozen=True)
class SandboxPolicy:
    """Declarative assertions; no check proves namespaces or cgroups exist."""

    network_namespace: bool = True
    readonly_host_mounts: bool = True
    deny_host_sockets: bool = True
    deny_credentials: bool = True
    private_tmp: bool = True
    no_new_privileges: bool = True
    memory_mib: int = 3072
    max_go_parallelism: int = 2
    timeout_seconds: int = 1200
    kill_process_group: bool = True
    cleanup_required: bool = True

    def validate(self) -> None:
        flags = (self.network_namespace, self.readonly_host_mounts,
                 self.deny_host_sockets, self.deny_credentials, self.private_tmp,
                 self.no_new_privileges, self.kill_process_group,
                 self.cleanup_required)
        if any(v is not True for v in flags):
            raise ContractError("sandbox_requirement_missing")
        if (type(self.memory_mib) is not int or not 1024 <= self.memory_mib <= 4096
                or type(self.max_go_parallelism) is not int
                or not 1 <= self.max_go_parallelism <= 2
                or type(self.timeout_seconds) is not int
                or not 60 <= self.timeout_seconds <= 1200):
            raise ContractError("resource_bounds_invalid")


@dataclass(frozen=True)
class DiagnosticPlan:
    request_id: str
    simulator_sha: str
    remote_sha: str
    workspace: str
    node: str = "gway-001"
    user: str = "arthe"
    arch: str = "arm64"
    resources: tuple[str, ...] = _RESOURCES
    policy: SandboxPolicy = SandboxPolicy()

    def validate(self) -> None:
        if not isinstance(self.request_id, str) or not _RECEIPT_ID.fullmatch(self.request_id):
            raise ContractError("request_id_invalid")
        if not all(isinstance(s, str) and _SHA.fullmatch(s)
                   for s in (self.simulator_sha, self.remote_sha)):
            raise ContractError("sha_invalid")
        if (self.node, self.user, self.arch) != ("gway-001", "arthe", "arm64"):
            raise ContractError("target_invalid")
        # V1-B is the only resource grammar. A complete-node claim is
        # intentional until compute, filesystem and process footprints are attested.
        if type(self.resources) is not tuple or self.resources != _RESOURCES:
            raise ContractError("resource_scope_invalid")
        try:
            if plan(self.resources).resources != self.resources:
                raise ContractError("resource_scope_invalid")
        except ResourceError:
            raise ContractError("resource_scope_invalid") from None
        if not isinstance(self.workspace, str) or "\x00" in self.workspace:
            raise ContractError("workspace_invalid")
        p = PurePosixPath(self.workspace)
        if (not p.is_absolute() or str(p) != self.workspace
                or len(p.parts) != 3 or p.parts[1] != "tmp"
                or p.parts[2] != f"go-diag-{self.request_id}"
                or any(s in (".", "..") for s in self.workspace.split("/"))):
            raise ContractError("workspace_invalid")
        if not isinstance(self.policy, SandboxPolicy):
            raise ContractError("policy_invalid")
        self.policy.validate()


def conceptual_conflicts(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    """V1-B pure overlap comparison, NEVER evidence of actual lock ownership.

    Require canonical tuples so duplicate or ancestor/descendant claims cannot
    silently change their meaning; malformed values fail closed.
    """
    if type(left) is not tuple or type(right) is not tuple:
        raise ContractError("resource_scope_invalid")
    try:
        a, b = plan(left), plan(right)
        if a.resources != left or b.resources != right:
            raise ContractError("resource_scope_invalid")
        return conflicts(a, b)
    except ResourceError:
        raise ContractError("resource_scope_invalid") from None


@dataclass(frozen=True)
class BarrierEvidence:
    """Untrusted declaration only; MUST be backed by runtime authority in D1."""

    schedule_covered: bool
    broker_covered: bool
    manual_covered: bool
    deployment_covered: bool
    owner_alive: bool
    no_competing_jobs: bool
    shared_lock_held: bool
    boot_verified: bool

    def validate_claims(self) -> None:
        if not all(v is True for v in (
            self.schedule_covered, self.broker_covered, self.manual_covered,
            self.deployment_covered, self.owner_alive,
            self.no_competing_jobs, self.shared_lock_held, self.boot_verified
        )):
            raise ContractError("barrier_evidence_missing")


def assess_offline(plan: DiagnosticPlan, claims: BarrierEvidence) -> str:
    """Return *design completeness* only, never admission to actual execution."""
    if not isinstance(plan, DiagnosticPlan) or not isinstance(claims, BarrierEvidence):
        raise ContractError("invalid_contract")
    plan.validate()
    claims.validate_claims()
    return "offline_contract_complete_not_runtime_authorization"


@dataclass(frozen=True)
class StepResult:
    name: str
    outcome: str
    exit_code: int | None = None

    def validate(self) -> None:
        if self.name not in _STEPS or self.outcome not in _ALLOWED_RESULTS:
            raise ContractError("step_invalid")
        if self.outcome == "not_run":
            if self.exit_code is not None:
                raise ContractError("step_code_invalid")
        elif (type(self.exit_code) is not int or not 0 <= self.exit_code <= 255
              or (self.outcome == "passed") != (self.exit_code == 0)):
            raise ContractError("step_code_invalid")


@dataclass(frozen=True)
class DiagnosticReceipt:
    request_id: str
    simulator_sha: str
    phase: Phase
    reason: str
    steps: tuple[StepResult, ...]
    workspace_removed: bool
    processes_reaped: bool

    def validate(self) -> None:
        if not isinstance(self.request_id, str) or not _RECEIPT_ID.fullmatch(self.request_id):
            raise ContractError("request_id_invalid")
        if not isinstance(self.simulator_sha, str) or not _SHA.fullmatch(self.simulator_sha):
            raise ContractError("sha_invalid")
        if self.phase not in (Phase.SUCCEEDED, Phase.FAILED, Phase.UNCERTAIN):
            raise ContractError("not_terminal")
        if self.reason not in _ALLOWED_CODES:
            raise ContractError("reason_invalid")
        if (type(self.steps) is not tuple or len(self.steps) != len(_STEPS)
                or any(not isinstance(s, StepResult) for s in self.steps)):
            raise ContractError("steps_invalid")
        for expected, step in zip(_STEPS, self.steps):
            step.validate()
            if step.name != expected:
                raise ContractError("step_order_invalid")
        seen_non_pass = False
        for step in self.steps:
            if seen_non_pass and step.outcome != "not_run":
                raise ContractError("continued_after_failure")
            if step.outcome != "passed":
                seen_non_pass = True
        complete = all(s.outcome == "passed" for s in self.steps)
        clean = self.workspace_removed is True and self.processes_reaped is True
        if self.phase is Phase.SUCCEEDED:
            if not complete or not clean or self.reason != "ok":
                raise ContractError("false_success")
        elif complete and clean and self.reason == "ok":
            raise ContractError("invalid_failure")
        if (self.workspace_removed is not True or self.processes_reaped is not True):
            if self.phase is not Phase.UNCERTAIN:
                raise ContractError("cleanup_uncertain")

    def sanitized(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": "go-diagnostic-receipt/d0",
            "request_id": self.request_id,
            "simulator_sha": self.simulator_sha,
            "phase": self.phase.value,
            "reason": self.reason,
            "steps": [{"name": s.name, "outcome": s.outcome,
                       "exit_code": s.exit_code} for s in self.steps],
            "workspace_removed": self.workspace_removed,
            "processes_reaped": self.processes_reaped,
        }
