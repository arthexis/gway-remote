"""Scoped execution authorization, identity checks and crash-safe deduplication."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets
import sqlite3

from .node_exec_contract import validate_command
from .node_exec_worker import validate_request_id
from .watchtower_exec_transport import RequestLedger, DormantRelay, HEX_SHA256, pinned_transport
from . import node_registry_inventory

_KEY_ID = re.compile(r"[0-9a-f]{24}")


def _now():
    return datetime.now(timezone.utc)


class AuthorizedExecution:
    """Execute-scoped authorization with current enrollment checks and durable deduplication."""

    def __init__(self, ledger, approvals, relay, *, enabled=False):
        self.ledger = ledger
        self.relay = relay
        self.enabled = enabled

    def _allow(self, principal):
        if not self.enabled or not self.relay.enabled:
            raise PermissionError("remote execution disabled")
        if type(principal) is not str or not _KEY_ID.fullmatch(principal):
            raise PermissionError("invalid execute principal")

    def _current_eligibility(self, node):
        """Fail closed against the root-published current enrollment projection."""
        pinned = pinned_transport(self.relay.transport, node).node
        inventory = node_registry_inventory.load()
        rows = [r for r in inventory["nodes"] if r["node"] == node]
        if (len(rows) != 1 or node != pinned.node or
                rows[0]["registered"] is not True or
                rows[0]["identity_verified"] is not True or
                rows[0]["execute_eligible"] is not True or
                rows[0]["reachable"] != "reachable" or
                rows[0]["address"] != pinned.wireguard_address):
            raise PermissionError("current enrolled execution eligibility denied")

    def exec(self, *, principal, request_id, node, command, wait_seconds=10):
        if type(wait_seconds) is not int or not 0 <= wait_seconds <= 10:
            raise ValueError("invalid inline wait")
        self._allow(principal)
        validate_request_id(request_id)
        validate_command(node, command)
        self._current_eligibility(node)
        # First insertion wins. Retrying an already known request ID never
        # redispatches, even when its status is uncertain or the process restarted.
        from datetime import timedelta
        try:
            prior = self.ledger.get(request_id)
        except ValueError as exc:
            if str(exc) != "request not found":
                raise
            prior = None
        if prior is not None:
            from .watchtower_exec_transport import _digest
            if (prior["node"] != node or prior["principal"] != principal or
                    prior["host_key_sha256"] != pinned_transport(self.relay.transport, node).node.host_key_sha256 or
                    prior["command_sha256"] != _digest(node, command, principal,
                        pinned_transport(self.relay.transport, node).node.host_key_sha256)):
                raise PermissionError("request ID already bound to another job")
            return {"request_id": request_id, "node": node, "status": prior["state"]}
        expiry = (_now() + timedelta(seconds=120)).isoformat()
        try:
            self.ledger.reserve(request_id=request_id, node=node, command=command,
                                principal=principal,
                                host_key_sha256=pinned_transport(self.relay.transport, node).node.host_key_sha256,
                                expires_at=expiry)
        except ValueError:
            # Another request with this ID may have won the atomic reservation.
            # Re-read and prove exact identity before returning; never redispatch.
            from .watchtower_exec_transport import _digest
            existing = self.ledger.get(request_id)
            if (existing["node"] != node or existing["principal"] != principal
                    or existing["host_key_sha256"] != pinned_transport(self.relay.transport, node).node.host_key_sha256
                    or existing["command_sha256"] != _digest(node, command, principal,
                        pinned_transport(self.relay.transport, node).node.host_key_sha256)):
                raise PermissionError("request ID already bound to another job")
            return {"request_id": request_id, "node": node, "status": existing["state"]}
        self._current_eligibility(node)
        dispatched = self.relay.dispatch(request_id)
        evidence = dispatched if type(dispatched) is dict else {}
        status = evidence.get("status") if evidence else dispatched
        response = {"request_id": request_id, "node": node, "status": status}
        if status == "uncertain" and evidence.get("failure_stage") in (
                "ssh_transport", "worker_readiness"):
            response["failure_stage"] = evidence["failure_stage"]
        if status != "dispatched" or wait_seconds == 0:
            return response
        import time
        deadline = time.monotonic() + wait_seconds
        while True:
            result = self.relay.result(request_id)
            if result.get("status") in {"succeeded", "failed", "cancelled", "timed_out"}:
                return result
            if result.get("result_available") is False or "status" not in result:
                return response
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return response
            time.sleep(min(0.2, remaining))

    def deployment_preview(self, *, node, application, revision="main"):
        """Query the installed provider on the pinned node, never a Watchtower allowlist."""
        from .mcp_deployment_resolver import _APP
        if type(node) is not str or type(application) is not str or not _APP.fullmatch(application) or revision != "main":
            raise ValueError("unsupported deployment revision or target")
        self._allow_preview_eligibility(node)
        import secrets
        request_id = secrets.token_hex(16)
        response = pinned_transport(self.relay.transport, node).invoke({
            "operation": "deployment_preview", "node": node,
            "request_id": request_id, "application": application})
        if (type(response) is not dict or response.get("node") != node or
                response.get("request_id") != request_id or
                type(response.get("result")) is not dict or
                response["result"].get("application") != application or
                response["result"].get("status") != "declared"):
            raise PermissionError("uncorrelated deployment preview")
        return {"node": node, "application": application, "revision": revision,
                "status": "eligible", "execution": "node-owned-operator",
                "note": "read-only; execution revalidates installed provider"}

    def _allow_preview_eligibility(self, node):
        if not self.enabled or not self.relay.enabled:
            raise PermissionError("deployment execution is not enabled")
        self._current_eligibility(node)

    def deployment(self, *, principal, request_id, node, application,
                   revision="main", status=False):
        """Deployment status is restricted to its original authenticated request.

        Execution remains disabled until the node-local asynchronous runner
        can persist a receipt before acknowledging an SSH dispatch.
        """
        from .mcp_deployment_resolver import _APP
        from .watchtower_exec_transport import _digest
        if type(status) is not bool:
            raise ValueError("invalid deployment status")
        self._allow(principal)
        validate_request_id(request_id)
        if (type(application) is not str or not _APP.fullmatch(application)
                or revision != "main"):
            raise ValueError("unsupported deployment target")
        self._current_eligibility(node)
        if status:
            row = self.ledger.get(request_id)
            pinned = pinned_transport(self.relay.transport, node)
            binding = "deployment:" + json.dumps([application, revision], separators=(",", ":"))
            if (row["node"] != node or row["principal"] != principal
                    or row["host_key_sha256"] != pinned.node.host_key_sha256
                    or row["command"] != binding
                    or row["command_sha256"] != _digest(
                        node, binding, principal, pinned.node.host_key_sha256)):
                raise PermissionError("deployment request binding mismatch")
            response = pinned.invoke({
                "operation": "deployment_status", "node": node,
                "request_id": request_id, "application": application})
            if (type(response) is not dict or response.get("node") != node or
                    response.get("request_id") != request_id or
                    type(response.get("result")) is not dict):
                raise PermissionError("uncorrelated deployment status")
            receipt = response["result"]
            if (receipt.get("application") != application or
                    receipt.get("request_id") != request_id or
                    type(receipt.get("revision")) is not str):
                raise PermissionError("deployment receipt binding mismatch")
            state = receipt.get("state")
            if state not in {"accepted", "running", "succeeded", "failed", "uncertain"}:
                raise PermissionError("invalid deployment receipt state")
            if state in {"succeeded", "failed"}:
                self.ledger.record_result_state(request_id, state)
            return {"node": node, "request_id": request_id,
                    "application": application,
                    "ledger_state": self.ledger.get(request_id)["state"],
                    "result": receipt}
        preview = self.deployment_preview(node=node, application=application,
                                          revision=revision)
        pinned = pinned_transport(self.relay.transport, node)
        binding = "deployment:" + json.dumps([application, revision], separators=(",", ":"))
        digest = _digest(node, binding, principal, pinned.node.host_key_sha256)
        try:
            prior = self.ledger.get(request_id)
        except ValueError as exc:
            if str(exc) != "request not found":
                raise
            prior = None
        if prior is not None:
            if (prior["node"] != node or prior["principal"] != principal
                    or prior["host_key_sha256"] != pinned.node.host_key_sha256
                    or prior["command"] != binding or prior["command_sha256"] != digest):
                raise PermissionError("deployment request ID binding mismatch")
            return {"node": node, "request_id": request_id, "application": application,
                    "status": prior["state"]}
        expiry = (_now() + timedelta(seconds=120)).isoformat()
        self.ledger.reserve_deployment(
            request_id=request_id, node=node, application=application,
            revision=revision, principal=principal,
            host_key_sha256=pinned.node.host_key_sha256, expires_at=expiry)
        self._current_eligibility(node)
        if not self.ledger.claim_dispatch(request_id):
            return {"node": node, "request_id": request_id, "application": application,
                    "status": self.ledger.get(request_id)["state"]}
        try:
            response = pinned.invoke({"operation": "deployment_run", "node": node,
                                      "request_id": request_id, "application": application})
            result = response.get("result") if type(response) is dict else None
            if (response.get("node") != node or response.get("request_id") != request_id
                    or type(result) is not dict or result.get("application") != application
                    or result.get("request_id") != request_id
                    or result.get("state") not in {"accepted", "running", "succeeded", "failed", "uncertain"}):
                raise PermissionError("uncorrelated deployment acknowledgement")
        except (OSError, ValueError, RuntimeError, PermissionError):
            # Never retry a potentially delivered request after a transport error.
            return {"node": node, "request_id": request_id, "application": application,
                    "status": "uncertain"}
        return {"node": node, "request_id": request_id, "application": application,
                "status": result["state"], "result": result}

    def _owned(self, principal, request_id):
        self._allow(principal)
        record = self.ledger.get(request_id)
        pinned_transport(self.relay.transport, record["node"])
        if record["principal"] != principal:
            raise PermissionError("request belongs to another principal")
        return record

    def result(self, *, principal, request_id, cursor=0):
        self._owned(principal, request_id)
        return self.relay.result(request_id, cursor)

    def cancel(self, *, principal, request_id):
        self._owned(principal, request_id)
        return self.relay.cancel(request_id)
