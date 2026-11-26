"""Private, durable idempotency journal for reviewed Android scenario runs.

Every mutation occurs under the existing device session lock. Atomic replacement
and directory fsync preserve a conservative claim across process termination.
No automatic expiry, replay, or eviction of operation identities.
"""
import json
import os
import stat
from pathlib import Path

from .android_execution_contract import valid_id

_MAX_OPERATIONS = 128
_MAX_BYTES = 4096
_STATES = {"claimed", "terminal", "reconciled"}


class OperationError(ValueError):
    pass


def _directory(root, create=False):
    from .android_scenario_runner import _private_dir
    root = _private_dir(Path(root), create=create)
    path = root / ".operations-v1"
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        raise OperationError("unsafe_operation_storage")
    return path


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > _MAX_BYTES):
            raise OperationError("unsafe_operation_record")
        raw = stream.read(_MAX_BYTES + 1)
    row = json.loads(raw)
    if (type(row) is not dict or len(raw) > _MAX_BYTES
            or row.get("schema") != "gway-android-operation/v1"
            or not valid_id(row.get("operation_id")) or path.name != row["operation_id"] + ".json"
            or row.get("state") not in _STATES or type(row.get("input_attempts")) is not int
            or not 0 <= row["input_attempts"] <= 2
            or type(row.get("scenario_id")) is not str
            or type(row.get("spec_sha256")) is not str or len(row["spec_sha256"]) != 64
            or (row.get("invocation_id") is not None and not valid_id(row["invocation_id"]))
            or (row.get("receipt_sha256") is not None and
                (type(row["receipt_sha256"]) is not str or len(row["receipt_sha256"]) != 64))):
        raise OperationError("invalid_operation_record")
    return row


def _write(directory, row):
    raw = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > _MAX_BYTES:
        raise OperationError("operation_record_too_large")
    path = directory / (row["operation_id"] + ".json")
    tmp = directory / ".write.tmp"
    try:
        info = tmp.lstat()
    except FileNotFoundError:
        pass
    else:
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise OperationError("unsafe_operation_temp")
        tmp.unlink()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _record(root, operation_id):
    if not valid_id(operation_id):
        raise OperationError("invalid_operation_id")
    try:
        return _read(_directory(root) / (operation_id + ".json"))
    except FileNotFoundError:
        return None


def _receipt(root, row):
    # A receipt committed just before a process died is recoverable by its
    # deterministic operation ID. Incomplete/corrupt receipts remain uncertain.
    from .android_scenario_runner import result
    try:
        receipt = result(row["operation_id"], root=root)
    except (OSError, ValueError, RuntimeError):
        return None
    manifest = receipt["manifest"]
    if (manifest.get("operation_id") != row["operation_id"]
            or manifest.get("scenario_id") != row["scenario_id"]
            or manifest.get("spec_sha256") != row["spec_sha256"]
            or manifest.get("status") not in ("passed", "failed")
            or type(manifest.get("action_invocations")) is not int
            or not row["input_attempts"] <= manifest["action_invocations"] <= 2
            or type(manifest.get("operations")) is not list
            or (row.get("invocation_id") is not None and
                (type(manifest.get("invocation_trace")) is not dict or
                 manifest["invocation_trace"].get("invocation_id") != row["invocation_id"]))
            or (row.get("receipt_sha256") is not None and
                row["receipt_sha256"] != receipt["sha256"])):
        return None
    return receipt


def status(root, operation_id):
    row = _record(root, operation_id)
    if row is None:
        return {"operation_id": operation_id, "status": "not_found",
                "retryable": False, "reconciliation_required": True}
    receipt = _receipt(root, row)
    base = {"operation_id": operation_id, "scenario_id": row["scenario_id"],
            "spec_sha256": row["spec_sha256"], "input_attempts": row["input_attempts"],
            "retryable": False}
    if row.get("invocation_id") is not None:
        base["invocation_id"] = row["invocation_id"]
    if row["state"] == "reconciled":
        base.update({"reconciled": True, "observed_screen": row["observed_screen"],
                     "reconciliation_required": False})
    else:
        base["reconciliation_required"] = (receipt is None or
            (receipt["manifest"]["status"] != "passed" and
             (row["input_attempts"] > 0 or receipt["manifest"]["action_invocations"] > 0)))
    if receipt is None:
        return {**base, "status": "uncertain"}
    manifest = receipt["manifest"]
    return {**base, "status": manifest["status"], "receipt_id": receipt["receipt_id"],
            "receipt_sha256": receipt["sha256"], "action_invocations": manifest["action_invocations"],
            "steps_completed": len(manifest["operations"]), "screenshots": "not_collected",
            "invocation_id": manifest.get("invocation_trace", {}).get("invocation_id")}


class Claim:
    def __init__(self, directory, row, action_budget):
        self.directory = directory
        self.row = row
        self.action_budget = action_budget

    @property
    def operation_id(self):
        return self.row["operation_id"]

    def input_attempt(self):
        if self.row["input_attempts"] >= self.action_budget:
            raise OperationError("operation_action_budget_exhausted")
        self.row["input_attempts"] += 1
        # Must succeed BEFORE the subprocess invocation. No best-effort bypass.
        _write(self.directory, self.row)

    def finish(self, result):
        if (result.get("receipt_id") != self.operation_id
                or type(result.get("receipt_sha256")) is not str
                or len(result["receipt_sha256"]) != 64):
            raise OperationError("invalid_terminal_receipt")
        self.row["receipt_sha256"] = result["receipt_sha256"]
        self.row["state"] = "terminal"
        _write(self.directory, self.row)


def begin(root, operation_id, scenario_id, digest, action_budget, *, invocation_id=None):
    """Return (claim, cached response); never execute an existing identity."""
    if not valid_id(operation_id):
        raise OperationError("invalid_operation_id")
    directory = _directory(root, create=True)
    previous = _record(root, operation_id)
    if previous is not None:
        if previous["scenario_id"] != scenario_id or previous["spec_sha256"] != digest:
            raise OperationError("operation_binding_conflict")
        return None, {**status(root, operation_id), "replayed": True}
    paths = list(directory.glob("*.json"))
    if len(paths) >= _MAX_OPERATIONS:
        raise OperationError("operation_storage_full")
    for path in paths:
        row = _read(path)
        if status(root, row["operation_id"])["reconciliation_required"]:
            return None, {"operation_id": operation_id, "status": "blocked",
                          "error": "previous_operation_unresolved",
                          "blocking_operation_id": row["operation_id"],
                          "retryable": False, "reconciliation_required": True}
    if (Path(root) / (operation_id + ".json")).exists() or (Path(root) / (operation_id + ".json")).is_symlink():
        raise OperationError("operation_receipt_collision")
    from .android_scenario_runner import _MAX_RECEIPTS
    if sum(1 for p in Path(root).iterdir() if p.name.endswith(".json")) >= _MAX_RECEIPTS:
        raise OperationError("receipt_storage_full")
    row = {"schema": "gway-android-operation/v1", "operation_id": operation_id,
           "scenario_id": scenario_id, "spec_sha256": digest,
           "state": "claimed", "input_attempts": 0}
    if valid_id(invocation_id):
        row["invocation_id"] = invocation_id
    _write(directory, row)
    return Claim(directory, row, action_budget), None


def reconcile(root, operation_id, expected_screen, device):
    """Record explicit physical observation; never resume or replay an operation."""
    from .android_navigation_model import SCREENS
    if expected_screen not in SCREENS:
        raise OperationError("invalid_expected_screen")
    row = _record(root, operation_id)
    if row is None:
        raise OperationError("operation_not_found")
    current = status(root, operation_id)
    if not current["reconciliation_required"]:
        return current
    observed = device.invoke("navigation_model", {})
    if observed.get("status") != "recognized" or observed.get("screen") != expected_screen:
        return {**current, "error": "reconciliation_screen_mismatch"}
    row.update({"state": "reconciled", "observed_screen": expected_screen})
    _write(_directory(root), row)
    return status(root, operation_id)
