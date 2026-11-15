"""MaintenanceFence V1-B: pure, exclusive resource-set planning only.

This module does NOT acquire locks, authenticate actors, persist receipts,
or grant permission to execute commands. It is safe to import in offline tests.
Every execution path must independently supply its complete resource footprint.
"""
from dataclasses import dataclass
import re

_NODE = re.compile(r"gway-[0-9]{3}|ocpp-abb-[0-9]+\Z")
_SEGMENT = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_ALLOWED_KINDS = frozenset(("deploy", "service", "network", "database", "filesystem", "maintenance"))
_MAX_RESOURCES = 32


class ResourceError(ValueError):
    """Sanitized rejection; never echo user-supplied resource identities."""

    def __init__(self):
        super().__init__("invalid_maintenance_resource_v1")


def _segments(resource):
    if type(resource) is not str or len(resource) > 255:
        raise ResourceError()
    parts = resource.split("/")
    if (len(parts) not in (2, 4)
            or parts[0] != "node"
            or _NODE.fullmatch(parts[1]) is None):
        raise ResourceError()
    if len(parts) == 4 and (
            parts[2] not in _ALLOWED_KINDS
            or _SEGMENT.fullmatch(parts[3]) is None):
        raise ResourceError()
    return tuple(parts)


def overlaps(a, b):
    """True when two exclusive resources are equal or ancestor/descendant."""
    x, y = _segments(a), _segments(b)
    common = min(len(x), len(y))
    return x[:common] == y[:common]


@dataclass(frozen=True)
class ResourcePlan:
    """Canonical, sorted set of exclusive resources; not an acquired lease."""

    resources: tuple[str, ...]

    def __post_init__(self):
        if (type(self.resources) is not tuple
                or not 1 <= len(self.resources) <= _MAX_RESOURCES):
            raise ResourceError()
        for resource in self.resources:
            _segments(resource)
        if tuple(sorted(set(self.resources))) != self.resources:
            raise ResourceError()
        # Plans cannot contain redundant ancestor/descendant entries.
        for index, resource in enumerate(self.resources):
            if any(overlaps(resource, other)
                   for other in self.resources[:index]):
                raise ResourceError()


def plan(resources):
    """Canonicalize input, replacing redundant descendants with ancestors.

    Refuses strings, empty sets, malformed names and unbounded input.
    This does not establish whether the declared footprint is complete.
    """
    if type(resources) not in (list, tuple, frozenset, set):
        raise ResourceError()
    if not 1 <= len(resources) <= _MAX_RESOURCES:
        raise ResourceError()
    raw = []
    for item in resources:
        _segments(item)
        raw.append(item)
    chosen = []
    for item in sorted(set(raw)):
        if any(overlaps(item, prior) for prior in chosen):
            continue
        chosen = [prior for prior in chosen if not overlaps(item, prior)]
        chosen.append(item)
    return ResourcePlan(tuple(sorted(chosen)))


def conflicts(left, right):
    """Pure conflict predicate; not a linearizable lock check."""
    if type(left) is not ResourcePlan or type(right) is not ResourcePlan:
        raise ResourceError()
    return any(overlaps(a, b) for a in left.resources for b in right.resources)


def acquire_order(resource_plan):
    """Deterministic lock-key order for a future *atomic* lock coordinator."""
    if type(resource_plan) is not ResourcePlan:
        raise ResourceError()
    return resource_plan.resources
