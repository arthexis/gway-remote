"""Offline last-state-only Fleet projection.

Caller MUST supply independently authenticated observations. No history,
network access, credential handling or read transport activation.
"""
from datetime import datetime, timezone, timedelta

class LatestFleetState:
    def __init__(self, *, ttl_seconds=300):
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise ValueError("invalid TTL")
        self.ttl_seconds = ttl_seconds
        self._nodes = {}

    def update(self, node, state, *, sequence, observed_at, authenticated=False):
        if authenticated is not True:
            raise PermissionError("unauthenticated fleet observation")
        if type(node) is not str or not node.startswith("gway-") or not node[5:].isdigit():
            raise ValueError("invalid node")
        if type(sequence) is not int or sequence < 0:
            raise ValueError("trusted sequence required")
        if type(observed_at) is not datetime or observed_at.tzinfo is None:
            raise ValueError("timezone-aware observation required")
        if type(state) is not dict:
            raise ValueError("invalid state")
        previous = self._nodes.get(node)
        if previous is not None:
            old_sequence, old_stamp, old_state = previous
            if sequence < old_sequence:
                return False
            if sequence == old_sequence:
                if observed_at != old_stamp or state != old_state:
                    raise ValueError("conflicting observation at same sequence")
                return False
            if observed_at < old_stamp:
                raise ValueError("nonmonotonic observation time")
        self._nodes[node] = (sequence, observed_at, dict(state))
        return True

    def snapshot(self, *, now=None):
        now = datetime.now(timezone.utc) if now is None else now
        if type(now) is not datetime or now.tzinfo is None:
            raise ValueError("timezone-aware now required")
        result = {}
        for node, (sequence, stamp, state) in self._nodes.items():
            age = (now - stamp).total_seconds()
            fresh = 0 <= age <= self.ttl_seconds
            result[node] = {"status": state if fresh else None,
                            "freshness": "current" if fresh else "stale",
                            "observed_at": stamp.isoformat(), "sequence": sequence}
        return result
