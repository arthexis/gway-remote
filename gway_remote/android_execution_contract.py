"""Reviewed Android scenario reliability: bounded deadlines and typed uncertainty.

No authentication inputs, raw arguments, device identifiers or UI content are
persisted. The public scope admission and device lock remain authoritative.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import re
import time

# Absolute runner budget; outer budgets include discovery/session setup and
# cleanup. Only the reviewed Android scenario_run path uses these overrides.
RUN_SECONDS = 40
STDIO_SECONDS = 50
SSH_SECONDS = 65
_ID = re.compile(r"[0-9a-f]{32}\Z")
_DEADLINE = ContextVar("android_scenario_deadline", default=None)
_OPERATION = ContextVar("android_scenario_operation", default=None)


def valid_id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def operation():
    return _OPERATION.get()


@contextmanager
def budget(*, seconds=RUN_SECONDS, clock=time.monotonic, claim=None):
    deadline = _DEADLINE.set((clock, clock() + seconds))
    current = _OPERATION.set(claim)
    try:
        yield
    finally:
        _OPERATION.reset(current)
        _DEADLINE.reset(deadline)


class DeadlineExceeded(RuntimeError):
    pass


def remaining():
    item = _DEADLINE.get()
    if item is None:
        return None
    clock, end = item
    return end - clock()


def limit_timeout(timeout):
    left = remaining()
    if left is None:
        return timeout
    if left <= 0:
        raise DeadlineExceeded("scenario_deadline")
    return min(timeout, left)


def uncertain_result(arguments, invocation_id, code):
    """Do not tell a caller to retry after an uncertain provider/SSH outcome."""
    body = {"status": "uncertain", "error": code, "retryable": False,
            "reconciliation_required": True}
    if type(arguments) is dict and valid_id(arguments.get("operation_id")):
        body["operation_id"] = arguments["operation_id"]
    if valid_id(invocation_id):
        body["invocation_id"] = invocation_id
    return {"content": [{"type": "text", "text": json.dumps(body, separators=(",", ":"))}]}
