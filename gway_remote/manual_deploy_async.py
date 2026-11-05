"""Asynchronous, idempotent deployment dispatch on the trusted Watchtower side.

This is a library boundary, not an HTTP endpoint. Its caller must authenticate
the execute principal and provide a trusted inventory snapshot. Never expose
the worker's process privileges to the MCP web service.
"""
from __future__ import annotations

import concurrent.futures
import threading

from .manual_deploy_broker import DeploymentReceipts, authorize_deploy
from .manual_deploy_git import resolve_sha
from .manual_deploy_recipe import execute_recipe

_WORKERS = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="gway-deploy")


class AsyncDeployBroker:
    def __init__(self, ledger: DeploymentReceipts, *, inventory, resolver=resolve_sha,
                 executor=execute_recipe, pool=None):
        self.ledger = ledger
        self.inventory = inventory
        self.resolver = resolver
        self.executor = executor
        self.pool = pool or _WORKERS
        self._lock = threading.Lock()
        self._active = set()

    def deploy(self, *, principal, request_id, repository, node, revision="main"):
        if type(principal) is not str or not principal:
            raise PermissionError("execute principal required")
        # Idempotent retries of a completed request must not resolve moving
        # main again. The receipt is already bound to its immutable SHA.
        try:
            prior = self.ledger.status(request_id, principal)
        except PermissionError:
            prior = None
        if prior is not None:
            if (prior["repository"], prior["node"]) != (repository, node):
                raise PermissionError("request ID already bound to another deployment")
            if revision != "main" and prior["sha"] != revision:
                raise PermissionError("request ID already bound to another revision")
            return prior
        approved = authorize_deploy(repository, node, revision,
                                    inventory=self.inventory(), resolve_sha=self.resolver)
        with self._lock:
            receipt = self.ledger.reserve(request_id, principal, approved)
            if receipt["state"] != "reserved":
                return receipt
            if not self.ledger.transition(request_id, "reserved", "running"):
                return self.ledger.status(request_id, principal)
            try:
                self.pool.submit(self._execute, request_id, repository, node, approved["sha"])
            except Exception:
                self.ledger.transition(request_id, "running", "unknown")
                raise
        return self.ledger.status(request_id, principal)

    def _execute(self, request_id, repository, node, sha):
        try:
            outcome = self.executor(repository, node, sha)
            state = outcome["state"]
            if state not in ("succeeded", "failed", "already_current"):
                state = "unknown"
        except Exception:
            state = "unknown"
        try:
            self.ledger.transition(request_id, "running", state)
        finally:
            with self._lock:
                self._active.discard(request_id)

    def status(self, *, principal, request_id):
        if type(principal) is not str or not principal:
            raise PermissionError("execute principal required")
        return self.ledger.status(request_id, principal)
