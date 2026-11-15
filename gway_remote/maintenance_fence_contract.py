"""MaintenanceFence V1-A: deterministic, in-memory contract ONLY.

No effective exclusion: no lock, persistence, authenticated principal source,
clock, coordination, journal, GitHub/API, subprocess, or runtime integration.
All independently verified identity/clock/authority values are caller inputs.
Never use this as a deployment admission check.
"""
from dataclasses import dataclass
import hashlib
import json
import re

VERSION = 1
_STATES = frozenset(("idle", "held", "uncertain", "terminal"))
_SOURCES = frozenset(("manual", "agentops", "schedule", "workflow"))
_NODE = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")
_REPO = re.compile(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_PRINCIPAL = re.compile(r"[0-9a-f]{24}\Z")
_REQUEST = re.compile(r"[0-9a-f]{32}\Z")
_BOOT = re.compile(r"[a-zA-Z0-9_-]{8,128}\Z")
_TOKEN = re.compile(r"[0-9a-f]{64}\Z")
_DIGEST = _TOKEN
_MAX_NS = (1 << 63) - 1


class FenceError(ValueError):
    """Sanitized rejection without untrusted data."""

    def __init__(self):
        super().__init__("invalid_maintenance_fence_v1")


def _match(value, pattern):
    return type(value) is str and pattern.fullmatch(value) is not None


def _integer(value, *, positive=False):
    return type(value) is int and (0 < value if positive else 0 <= value) and value <= _MAX_NS


def _valid_identity(node, repo, sha, principal, source, request_id, boot_id):
    if not (_match(node, _NODE) and _match(repo, _REPO)
            and _match(sha, _SHA) and _match(principal, _PRINCIPAL)
            and type(source) is str and source in _SOURCES
            and _match(request_id, _REQUEST) and _match(boot_id, _BOOT)):
        raise FenceError()


def _hash(payload):
    try:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        raise FenceError() from None
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Claim:
    node: str
    repo: str
    sha: str
    principal: str
    source: str
    request_id: str
    boot_id: str
    generation: int
    token: str
    lease_until_ns: int

    def __post_init__(self):
        _valid_identity(self.node, self.repo, self.sha, self.principal,
                        self.source, self.request_id, self.boot_id)
        if (not _integer(self.generation, positive=True)
                or not _match(self.token, _TOKEN)
                or not _integer(self.lease_until_ns, positive=True)):
            raise FenceError()


@dataclass(frozen=True)
class Receipt:
    event: str
    state: str
    generation: int
    request_id: str
    digest: str

    def __post_init__(self):
        if (self.event not in ("acquired", "renewed", "completed", "uncertain", "recovered")
                or type(self.event) is not str
                or type(self.state) is not str or self.state not in _STATES
                or not _integer(self.generation)
                or not _match(self.request_id, _REQUEST)
                or not _match(self.digest, _DIGEST)):
            raise FenceError()


@dataclass(frozen=True)
class Fence:
    state: str = "idle"
    claim: Claim | None = None
    generation: int = 0
    receipt: Receipt | None = None

    def __post_init__(self):
        if (type(self.state) is not str or self.state not in _STATES
                or not _integer(self.generation)
                or (self.claim is not None and type(self.claim) is not Claim)
                or (self.receipt is not None and type(self.receipt) is not Receipt)):
            raise FenceError()
        if self.state == "idle":
            if self.claim is not None or self.receipt is not None or self.generation != 0:
                raise FenceError()
        elif (self.claim is None or self.receipt is None
              or self.claim.generation != self.generation
              or self.receipt.generation != self.generation
              or self.receipt.state != self.state):
            raise FenceError()


def _receipt(event, state, claim, *, reason):
    return Receipt(event, state, claim.generation, claim.request_id,
                   _hash({"version": VERSION, "event": event, "state": state,
                          "claim": claim.__dict__, "reason": reason}))


def _fence(state, claim, event, reason):
    return Fence(state, claim, claim.generation, _receipt(event, state, claim, reason=reason))


def token_for(*, node, repo, sha, principal, source, request_id, boot_id, generation):
    """Deterministic correlation token, NOT a cryptographic authorization capability."""
    _valid_identity(node, repo, sha, principal, source, request_id, boot_id)
    if not _integer(generation, positive=True):
        raise FenceError()
    return _hash({"version": VERSION, "node": node, "repo": repo, "sha": sha,
                  "principal": principal, "source": source,
                  "request_id": request_id, "boot_id": boot_id,
                  "generation": generation})


def make_claim(*, node, repo, sha, verified_principal, source, request_id,
               boot_id, generation, lease_until_ns):
    """verified_principal MUST be derived independently from authenticated authority."""
    token = token_for(node=node, repo=repo, sha=sha, principal=verified_principal,
                      source=source, request_id=request_id, boot_id=boot_id,
                      generation=generation)
    return Claim(node, repo, sha, verified_principal, source, request_id,
                 boot_id, generation, token, lease_until_ns)


def acquire(fence, claim, *, now_ns):
    """Acquire ONLY a pure snapshot; duplicate returns identical immutable receipt."""
    _inputs(fence, claim, now_ns)
    if fence.state == "idle":
        if claim.generation != 1 or now_ns >= claim.lease_until_ns:
            raise FenceError()
        return _fence("held", claim, "acquired", "initial")
    if fence.state == "held" and fence.claim == claim and now_ns < claim.lease_until_ns:
        return fence
    if fence.state == "uncertain":
        return fence
    if fence.state == "terminal":
        return fence  # Terminal is never reopened by acquire.
    return _fence("uncertain", fence.claim, "uncertain", "conflicting_or_expired_acquire")


def _inputs(fence, claim, now_ns):
    if type(fence) is not Fence or type(claim) is not Claim or not _integer(now_ns):
        raise FenceError()
    expected = token_for(node=claim.node, repo=claim.repo, sha=claim.sha,
                         principal=claim.principal, source=claim.source,
                         request_id=claim.request_id, boot_id=claim.boot_id,
                         generation=claim.generation)
    if claim.token != expected:
        raise FenceError()


def advance(fence, claim, *, now_ns, action, lease_until_ns=None):
    """Renew/complete/fault, with strict fencing and monotonic lease checks."""
    _inputs(fence, claim, now_ns)
    if type(action) is not str or action not in ("renew", "complete", "fault"):
        raise FenceError()
    if fence.state in ("uncertain", "terminal"):
        return fence
    if fence.state != "held":
        raise FenceError()
    if fence.claim != claim or now_ns >= fence.claim.lease_until_ns:
        return _fence("uncertain", fence.claim, "uncertain", "stale_or_expired")
    if action == "fault":
        return _fence("uncertain", claim, "uncertain", "fault")
    if action == "complete":
        return _fence("terminal", claim, "completed", "success")
    if not (_integer(lease_until_ns, positive=True)
            and lease_until_ns > claim.lease_until_ns
            and lease_until_ns > now_ns):
        raise FenceError()
    renewed = Claim(claim.node, claim.repo, claim.sha, claim.principal,
                    claim.source, claim.request_id, claim.boot_id,
                    claim.generation, claim.token, lease_until_ns)
    return _fence("held", renewed, "renewed", "lease_extended")


def observe(fence, *, now_ns, observed_boot_id=None):
    """External clock/boot observation; uncertainty cannot be auto-cleared."""
    if type(fence) is not Fence or not _integer(now_ns):
        raise FenceError()
    if observed_boot_id is not None and not _match(observed_boot_id, _BOOT):
        raise FenceError()
    if fence.state != "held":
        return fence
    if now_ns >= fence.claim.lease_until_ns or (
            observed_boot_id is not None and observed_boot_id != fence.claim.boot_id):
        return _fence("uncertain", fence.claim, "uncertain", "lease_or_boot_changed")
    return fence


def recover(fence, *, verified_admin, expected_generation, expected_digest,
            new_generation):
    """Document an external administrative decision; NEVER releases a real lock.

    The caller must independently verify admin authority and physical quiescence.
    This pure helper cannot verify either. A recovery is a terminal tombstone.
    """
    if (type(fence) is not Fence or fence.state != "uncertain"
            or not _match(verified_admin, _PRINCIPAL)
            or not _integer(expected_generation, positive=True)
            or not _match(expected_digest, _DIGEST)
            or not _integer(new_generation, positive=True)
            or new_generation <= expected_generation
            or fence.generation != expected_generation
            or fence.receipt.digest != expected_digest):
        raise FenceError()
    tombstone = Claim(fence.claim.node, fence.claim.repo, fence.claim.sha,
                      fence.claim.principal, fence.claim.source,
                      fence.claim.request_id, fence.claim.boot_id,
                      new_generation,
                      token_for(node=fence.claim.node, repo=fence.claim.repo,
                                sha=fence.claim.sha, principal=fence.claim.principal,
                                source=fence.claim.source, request_id=fence.claim.request_id,
                                boot_id=fence.claim.boot_id, generation=new_generation),
                      fence.claim.lease_until_ns)
    receipt = Receipt("recovered", "terminal", new_generation, tombstone.request_id,
                      _hash({"version": VERSION, "event": "recovered",
                             "previous_digest": expected_digest,
                             "admin": verified_admin,
                             "generation": new_generation, "claim": tombstone.__dict__}))
    return Fence("terminal", tombstone, new_generation, receipt)
