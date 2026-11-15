"""MaintenanceFence V1-C2 OFFLINE consistency checks, never authority.

Trusted arguments MUST come from independently authenticated/node-local
verifiers, not from the request payload. No execution permission is issued.
"""
from dataclasses import dataclass
import hashlib
import json
import re

from .maintenance_fence_contract import FenceError, make_claim
from .maintenance_fence_resources import ResourceError, plan

_HEX24 = re.compile(r"[0-9a-f]{24}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_BOOT = re.compile(r"[a-zA-Z0-9_-]{8,128}\Z")
_MAX_NS = (1 << 63) - 1
_MAX_SAMPLE_NS = 1_000_000_000
_FIELDS = frozenset(("node", "repo", "sha", "verified_principal", "source",
                     "request_id", "boot_id", "lease_until_ns"))


class ProvenanceError(ValueError):
    def __init__(self):
        super().__init__("invalid_maintenance_provenance_v1c2")


def _num(value):
    return type(value) is int and 0 <= value <= _MAX_NS


def _hex(value, pattern):
    return type(value) is str and pattern.fullmatch(value) is not None


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("ascii")
    except (ValueError, TypeError, UnicodeError):
        raise ProvenanceError() from None


@dataclass(frozen=True)
class BootSample:
    boot_id: str
    now_ns: int

    def __post_init__(self):
        if not _hex(self.boot_id, _BOOT) or not _num(self.now_ns):
            raise ProvenanceError()


def sample_local_boot(*, read_boot, monotonic_ns):
    """Cross-check boot ID around a monotonic clock reading. Pure injection."""
    try:
        before_ns = monotonic_ns()
        boot_before = read_boot()
        middle_ns = monotonic_ns()
        boot_after = read_boot()
        after_ns = monotonic_ns()
        if not all(_num(n) for n in (before_ns, middle_ns, after_ns)):
            raise ProvenanceError()
        if (not before_ns <= middle_ns <= after_ns
                or after_ns - before_ns > _MAX_SAMPLE_NS
                or boot_before != boot_after):
            raise ProvenanceError()
        return BootSample(boot_before, middle_ns)
    except (OSError, ValueError, TypeError, OverflowError):
        raise ProvenanceError() from None


def validate_claimed_binding(binding, *, trusted_principal, trusted_node,
                             trusted_repo, trusted_sha, trusted_source,
                             trusted_request_id, trusted_resources,
                             trusted_sample):
    """Compare payload with independent caller-verified facts; return digest only."""
    if type(binding) is not dict or set(binding) != _FIELDS:
        raise ProvenanceError()
    if type(trusted_sample) is not BootSample:
        raise ProvenanceError()
    try:
        make_claim(**binding, generation=1)
        resources = plan(trusted_resources).resources
    except (FenceError, ResourceError, ValueError, TypeError):
        raise ProvenanceError() from None
    expected = (trusted_principal, trusted_node, trusted_repo, trusted_sha,
                trusted_source, trusted_request_id)
    claimed = (binding["verified_principal"], binding["node"], binding["repo"],
               binding["sha"], binding["source"], binding["request_id"])
    if expected != claimed or binding["boot_id"] != trusted_sample.boot_id:
        raise ProvenanceError()
    if trusted_sample.now_ns >= binding["lease_until_ns"]:
        raise ProvenanceError()
    if any(resource.split("/")[1] != trusted_node for resource in resources):
        raise ProvenanceError()
    return hashlib.sha256(_canonical({
        "version": "v1c2", "binding": binding, "resources": list(resources),
        "sample": {"boot_id": trusted_sample.boot_id,
                   "now_ns": trusted_sample.now_ns}})).hexdigest()


def validate_recovery_record(record, *, trusted_admin, trusted_node,
                             trusted_receipt_digest, trusted_evidence_digest):
    """Metadata consistency only: no real quiescence or administrator check."""
    fields = {"request_id", "node", "admin", "receipt_digest", "evidence_digest"}
    if type(record) is not dict or set(record) != fields:
        raise ProvenanceError()
    if (not _hex(record["request_id"], _HEX32)
            or not _hex(record["admin"], _HEX24)
            or not _hex(record["receipt_digest"], _HEX64)
            or not _hex(record["evidence_digest"], _HEX64)
            or record["admin"] != trusted_admin
            or record["node"] != trusted_node
            or record["receipt_digest"] != trusted_receipt_digest
            or record["evidence_digest"] != trusted_evidence_digest):
        raise ProvenanceError()
    if type(trusted_node) is not str or not trusted_node.startswith("gway-"):
        raise ProvenanceError()
    return hashlib.sha256(_canonical({"version": "v1c2", "recovery": record})).hexdigest()
