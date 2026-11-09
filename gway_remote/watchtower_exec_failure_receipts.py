"""Bounded, sanitized, request-scoped execution failure receipts.

In-memory only: a restart or missing receipt is unknown, never success.
"""
from __future__ import annotations

import re
import threading
import time

REQUEST_ID = re.compile(r"[0-9a-f]{32}\Z")
STAGES = frozenset(("auth_scope", "current_eligibility", "pinned_transport",
                    "bridge_dispatch", "ssh_transport", "worker_readiness"))
OUTCOMES = frozenset(("failure", "blocked", "unknown"))
TTL_SECONDS = 300
MAX_ENTRIES = 512


class ExecutionStageError(PermissionError):
    """Safe stage marker; no underlying exception text is ever serialized."""

    def __init__(self, stage):
        if stage not in STAGES:
            raise ValueError("invalid diagnostic stage")
        super().__init__("execution denied")
        self.stage = stage


class FailureReceipts:
    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._rows = {}

    def record(self, request_id, principal, stage, outcome="failure"):
        if (type(request_id) is not str or not REQUEST_ID.fullmatch(request_id)
                or type(principal) is not str or not principal
                or stage not in STAGES or outcome not in OUTCOMES):
            return False
        with self._lock:
            now = self._clock()
            self._rows = {key: value for key, value in self._rows.items()
                          if value[0] > now}
            existing = self._rows.get(request_id)
            # First receipt wins for this request ID. Retries cannot overwrite
            # a confirmed failure with unknown or extend the original TTL.
            if existing is not None:
                return False
            if len(self._rows) >= MAX_ENTRIES:
                self._rows.pop(next(iter(self._rows)))
            self._rows[request_id] = (now + TTL_SECONDS, principal, stage, outcome)
        return True

    def inspect(self, request_id, principal):
        if type(request_id) is not str or not REQUEST_ID.fullmatch(request_id):
            raise ValueError("invalid request id")
        if type(principal) is not str or not principal:
            raise PermissionError("missing principal")
        with self._lock:
            now = self._clock()
            row = self._rows.get(request_id)
            if row is None or row[0] <= now:
                return {"request_id": request_id, "status": "unknown"}
            if row[1] != principal:
                # Do not reveal whether another principal has a receipt.
                return {"request_id": request_id, "status": "unknown"}
            return {"request_id": request_id, "status": row[3], "stage": row[2]}
