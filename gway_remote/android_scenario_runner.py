"""Reviewed Android acceptance scenarios, with private, sanitized receipts.

No caller-supplied steps, paths, shell, URLs, selectors, APK installs or screenshots.
The existing Android provider owns device operations and their OAuth scope;
this module owns only immutable recipe lookup, bounded execution and receipts.
"""
from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import stat
import time
import uuid

from . import android_navigation_model as navigation
from . import android_invocation_trace as diagnostics
from . import android_execution_contract as execution
from pathlib import Path

SCHEMA = "gway-android-scenario/v1"
RECEIPT_SCHEMA = "gway-android-scenario-receipt/v1"
_MAX_STEPS = 5
_MAX_RECEIPTS = 128
_MAX_RECEIPT_BYTES = 8192
_RUN_ID = re.compile(r"[0-9a-f]{32}\Z")

# Every scenario is reviewed as source in GWay Remote. Never take a scenario
# specification from a tool request or from a mutable user workspace.
SCENARIOS = {
    "developer-options-from-search-v1": (
        {"op": "semantic_transition", "from": "settings_search", "to": "settings_search_results"},
        {"op": "semantic_transition", "from": "settings_search_results", "to": "developer_options"},
    ),
    "developer-options-observation-v1": (
        {"op": "navigation_model", "expect": {"screen": "developer_options"}},
    ),
    "usb-readiness-v1": (
        {"op": "status", "expect": {"usb": "authorized"}},
    ),
    # No physical action is run by CI; the stage 5 field acceptance can use
    # this non-destructive key navigation after operator observation.
    "home-screen-stability-v1": (
        {"op": "status", "expect": {
            "usb": "authorized", "screen_on": True, "locked": False,
        }},
        {"op": "key", "args": {"key": "HOME"}},
        {"op": "status", "expect": {
            "usb": "authorized", "screen_on": True, "locked": False,
        }},
    ),
    # Reviewed v2 can wake an already authorized USB device once, without
    # altering v1's immutable steps, digest or historical receipts.
    "home-screen-stability-v2": (
        {"op": "status", "expect": {"usb": "authorized"}},
        {"op": "wake_if_needed"},
        {"op": "status", "expect": {
            "usb": "authorized", "screen_on": True, "locked": False,
        }},
        {"op": "key", "args": {"key": "HOME"}},
        {"op": "status", "expect": {
            "usb": "authorized", "screen_on": True, "locked": False,
        }},
    ),
}
_ALLOWED_OPS = frozenset({"status", "wait_ui", "tap_target", "key", "wake_if_needed", "navigation_model", "semantic_transition"})


_TRANSITION_REASONS = frozenset({
    "unsafe_device", "source_not_actionable", "target_changed", "device_changed",
    "preflight_error", "dispatch_uncertain", "verification_error",
    "destination_unconfirmed",
})


class ScenarioError(ValueError):
    pass


def _stable(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _spec(scenario_id):
    if type(scenario_id) is not str or scenario_id not in SCENARIOS:
        raise ScenarioError("scenario_not_reviewed")
    steps = SCENARIOS[scenario_id]
    if not isinstance(steps, tuple) or not 1 <= len(steps) <= _MAX_STEPS:
        raise ScenarioError("invalid_scenario")
    actions = 0
    for step in steps:
        if type(step) is not dict or step.get("op") not in _ALLOWED_OPS:
            raise ScenarioError("invalid_scenario")
        if step["op"] in ("key", "tap_target"):
            actions += 1
            if type(step.get("args")) is not dict:
                raise ScenarioError("invalid_scenario")
        elif step["op"] == "wake_if_needed":
            # One possible WAKEUP, never supplied by the MCP caller.
            if set(step) != {"op"}:
                raise ScenarioError("invalid_scenario")
            actions += 1
        elif step["op"] == "wait_ui" and type(step.get("args")) is not dict:
            raise ScenarioError("invalid_scenario")
        elif step["op"] == "status" and type(step.get("expect")) is not dict:
            raise ScenarioError("invalid_scenario")
        elif step["op"] == "semantic_transition":
            if (set(step) != {"op", "from", "to"}
                    or (step["from"], step["to"]) not in navigation.EXECUTABLE_EDGES):
                raise ScenarioError("invalid_scenario")
            actions += 1
        elif step["op"] == "navigation_model":
            if (set(step) != {"op", "expect"} or type(step["expect"]) is not dict
                    or set(step["expect"]) != {"screen"}
                    or step["expect"]["screen"] not in navigation.SCREENS):
                raise ScenarioError("invalid_scenario")
    if actions > 2:
        raise ScenarioError("invalid_scenario")
    spec = {"schema": SCHEMA, "id": scenario_id, "steps": steps}
    digest = hashlib.sha256(_stable(spec).encode("utf-8")).hexdigest()
    return steps, digest, actions


def preview(scenario_id):
    steps, digest, actions = _spec(scenario_id)
    return {
        "schema": SCHEMA,
        "scenario_id": scenario_id,
        "spec_sha256": digest,
        "step_types": [step["op"] for step in steps],
        "actions": actions,
        "run_scope": "gway:execute", "contains_actions": bool(actions),
        "operation_id_required": bool(actions),
        "screenshots": "not_collected",
        "execution": "not_started",
    }


def _receipt_root():
    # Do not trust a mutable HOME environment variable.
    return Path(pwd.getpwuid(os.geteuid()).pw_dir) / (
        ".local/state/gway-remote/android-harness/receipts"
    )


def _private_dir(root, *, create):
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    meta = root.lstat()
    if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid()
            or meta.st_mode & 0o077 or root.is_symlink()):
        raise ScenarioError("unsafe_receipt_directory")
    return root


def _write(root, manifest, *, receipt_id=None):
    _private_dir(root, create=True)
    if sum(1 for p in root.iterdir() if p.name.endswith(".json")) >= _MAX_RECEIPTS:
        raise ScenarioError("receipt_storage_full")
    encoded = _stable(manifest).encode("utf-8")
    if not 0 < len(encoded) <= _MAX_RECEIPT_BYTES:
        raise ScenarioError("receipt_too_large")
    receipt_id = uuid.uuid4().hex if receipt_id is None else receipt_id
    if not execution.valid_id(receipt_id):
        raise ScenarioError("invalid_receipt_id")
    target = root / (receipt_id + ".json")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return receipt_id, hashlib.sha256(encoded).hexdigest()


def result(receipt_id, *, root=None):
    if type(receipt_id) is not str or not _RUN_ID.fullmatch(receipt_id):
        raise ScenarioError("invalid_receipt_id")
    directory = _private_dir(root or _receipt_root(), create=False)
    path = directory / (receipt_id + ".json")
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077 or info.st_size > _MAX_RECEIPT_BYTES):
        raise ScenarioError("invalid_receipt")
    # No symbolic links, even in an otherwise private directory.
    if path.is_symlink():
        raise ScenarioError("invalid_receipt")
    with path.open("rb") as stream:
        raw = stream.read(_MAX_RECEIPT_BYTES + 1)
    if len(raw) > _MAX_RECEIPT_BYTES:
        raise ScenarioError("invalid_receipt")
    manifest = json.loads(raw)
    if (type(manifest) is not dict or manifest.get("schema") != RECEIPT_SCHEMA
            or manifest.get("scenario_id") not in SCENARIOS):
        raise ScenarioError("invalid_receipt")
    return {"receipt_id": receipt_id, "sha256": hashlib.sha256(raw).hexdigest(),
            "manifest": manifest}


def run(scenario_id, *, device, receipt_root=None, clock=time.monotonic):
    """Bounded execution; failure after a dispatched action is never retried."""
    steps, digest, actions = _spec(scenario_id)
    root = _private_dir(receipt_root or _receipt_root(), create=True)
    if sum(p.name.endswith(".json") for p in root.iterdir()) >= _MAX_RECEIPTS:
        raise ScenarioError("receipt_storage_full")
    started = clock()
    diagnostics.mark("runner_start")
    traces = []
    outcome = "passed"
    invocations = 0
    for index, step in enumerate(steps):
        # Five steps only; no CLI, remote input payload, arbitrary shell or loop.
        left = execution.remaining()
        if ((left is not None and left <= 0) or
                (left is None and clock() - started > (execution.RUN_SECONDS if actions else 7))):
            traces.append({"operation": "deadline", "outcome": "unknown"})
            outcome = "failed"
            break
        name = step["op"]
        diagnostics.mark("runner_step_begin", step=index, operation=name)
        verdict = "failed"
        transition = None
        if name == "semantic_transition":
            # Reserve an invocation before entering the provider; unexpected
            # exceptions cannot be treated as proof that nothing was sent.
            transition = {"dispatch": "uncertain", "reason": "provider_error"}
        try:
            if name == "status":
                observed = device.invoke("status", {})
                verdict = ("passed" if all(
                    observed.get(key) == value
                    for key, value in step["expect"].items()
                ) else "failed")
            elif name == "semantic_transition":
                # The device resolves a fresh unique target, dispatches at most once,
                # then verifies the destination. Count uncertain dispatch conservatively.
                invocations += 1
                observed = device.semantic_transition(step["from"], step["to"])
                dispatched = observed.get("dispatched")
                reason = observed.get("reason")
                if dispatched is False:
                    invocations -= 1
                    transition = {"dispatch": "not_attempted"}
                elif dispatched is True:
                    transition = {"dispatch": "attempted"}
                if isinstance(reason, str) and reason in _TRANSITION_REASONS:
                    transition["reason"] = reason
                if reason == "dispatch_uncertain" and dispatched is True:
                    transition["dispatch"] = "uncertain"
                verdict = ("passed" if dispatched is True
                           and observed.get("status") == "confirmed" else "failed")
            elif name == "navigation_model":
                observed = device.invoke("navigation_model", {})
                verdict = ("passed" if observed.get("status") == "recognized"
                           and observed.get("screen") == step["expect"]["screen"] else "failed")
            elif name == "wake_if_needed":
                # Reserve one possible dispatch before calling the device;
                # on uncertainty, conservatively count it as attempted.
                invocations += 1
                observed = device.wake_if_needed()
                if observed.get("woke") is False:
                    invocations -= 1
                verdict = "passed" if observed.get("ok") is True else "failed"
            else:
                if name in ("tap_target", "key"):
                    invocations += 1
                observed = device.invoke(name, dict(step["args"]))
                if name == "tap_target":
                    verdict = "passed" if observed.get("verification") == "confirmed" else "failed"
                elif name == "wait_ui":
                    verdict = "passed" if observed.get("status") == "confirmed" else "failed"
                else:
                    verdict = "passed" if observed.get("ok") is True else "failed"
        except (OSError, ValueError, RuntimeError, TimeoutError):
            verdict = "unknown"
        # Never include UI text, device serial, target id, screenshot or raw error.
        trace = {"operation": name, "outcome": verdict}
        if transition is not None:
            trace.update(transition)
        traces.append(trace)
        diagnostics.mark("runner_step_end", step=index, operation=name,
                         outcome=verdict, action_invocations=invocations,
                         **(transition or {}))
        if verdict != "passed":
            outcome = "failed"
            break
    elapsed = round(max(0, min(clock() - started, 60)) * 1000)
    manifest = {
        "schema": RECEIPT_SCHEMA, "scenario_id": scenario_id,
        "spec_sha256": digest, "status": outcome,
        "operations": traces, "action_invocations": invocations,
        "duration_ms": elapsed, "screenshots": "not_collected",
    }
    diagnostics.mark("runner_finish", outcome=outcome, action_invocations=invocations)
    invocation = diagnostics.current()
    if invocation is not None:
        manifest["invocation_trace"] = invocation.evidence()
    claim = execution.operation()
    if claim is not None:
        manifest["operation_id"] = claim.operation_id
    receipt_id, digest = _write(root, manifest, receipt_id=claim.operation_id if claim else None)
    result = {"status": outcome, "receipt_id": receipt_id,
              "receipt_sha256": digest, "steps_completed": len(traces),
              "action_invocations": invocations, "screenshots": "not_collected"}
    if invocation is not None:
        result["invocation_id"] = invocation.invocation_id
    if claim is not None:
        result["operation_id"] = claim.operation_id
    return result
