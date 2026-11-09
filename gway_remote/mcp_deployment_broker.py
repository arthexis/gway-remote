"""Node-local deployment broker for root-provisioned MCP providers.

The authenticated node protocol may invoke run as its existing effective user;
Watchtower must never supply
runner paths, arbitrary arguments, or environment variables.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import sys
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta

from .mcp_deployment_resolver import resolve_deployment

STATE_DIR = Path("/var/lib/gway-mcp-deploy")
LOCK_NAME = ".managed-provider.lock"


def _trusted(path, *, executable=False, directory=False):
    target = Path(path)
    if target.is_symlink() or any(parent.is_symlink() for parent in target.parents):
        raise PermissionError("symlink deployment path denied")
    info = target.stat()
    if info.st_mode & 0o022 or info.st_uid not in (0, os.geteuid()):
        raise PermissionError("untrusted deployment path owner or mode")
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise PermissionError("deployment checkout is not a directory")
    elif not stat.S_ISREG(info.st_mode) or (executable and not info.st_mode & 0o111):
        raise PermissionError("unsafe deployment runner")
    return target


def _receipt_path(application, state_dir):
    return state_dir / ("status-" + application + ".json")


def _write_receipt(path, payload):
    _trusted(path.parent, directory=True)
    if path.is_symlink():
        raise PermissionError("symlink receipt denied")
    if path.exists():
        _trusted(path)
    fd, tmp = tempfile.mkstemp(prefix=".deploy-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(payload, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _eligible(application, *, resolve=resolve_deployment):
    deployment = resolve(application)
    checkout = _trusted(deployment["checkout"], directory=True)
    runner = _trusted(deployment["runner"], executable=True)
    if not runner.is_relative_to(checkout):
        raise PermissionError("runner outside checkout")
    # The repository owns checkout updates, staging, Ansible and activated-SHA
    # verification. The broker must not confuse the installed MCP revision
    # with the target deployment revision.
    for parent in (checkout, *tuple(p for p in runner.parents
                                   if p == checkout or checkout in p.parents)):
        _trusted(parent, directory=True)
    return deployment


def preview(application, *, resolve=resolve_deployment):
    declaration = resolve(application)
    return {"application": application, "revision": declaration["revision"],
            "status": "declared", "execution": "current-node-identity",
            "note": "read-only declaration; execution revalidates node-local state"}


def status(application, *, state_dir=STATE_DIR, resolve=resolve_deployment):
    resolve(application)
    path = _receipt_path(application, state_dir)
    if path.is_symlink():
        raise PermissionError("symlink receipt denied")
    _trusted(path.parent, directory=True)
    if path.parent.stat().st_uid != os.geteuid() or path.parent.stat().st_mode & 0o077:
        raise PermissionError("deployment receipt directory must be private to operator")
    if not path.exists():
        return {"application": application, "state": "never_run"}
    _trusted(path)
    with path.open("r", encoding="utf-8") as stream:
        receipt = json.load(stream)
    if (type(receipt) is not dict or receipt.get("application") != application
            or receipt.get("state") not in {"running", "succeeded", "failed"}):
        raise ValueError("invalid deployment receipt")
    return receipt


def run(application, *, state_dir=STATE_DIR, resolve=resolve_deployment, invoke=subprocess.run):
    declaration = _eligible(application, resolve=resolve)
    _trusted(state_dir, directory=True)
    if state_dir.stat().st_uid != os.geteuid() or state_dir.stat().st_mode & 0o077:
        raise PermissionError("deployment state directory must be private to operator")
    lock_path = state_dir / LOCK_NAME
    if lock_path.is_symlink():
        raise PermissionError("symlink lock denied")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if (not stat.S_ISREG(os.fstat(fd).st_mode) or
                os.fstat(fd).st_uid != os.geteuid() or os.fstat(fd).st_mode & 0o077):
            raise PermissionError("untrusted lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Recheck after acquiring lock; a concurrent deployment may have
        # changed the checkout or installed declaration.
        if _eligible(application, resolve=resolve) != declaration:
            raise PermissionError("deployment declaration changed")
        path = _receipt_path(application, state_dir)
        # A successful receipt is historical evidence, not proof that the
        # requested target is currently active. The provider deploy is idempotent.
        started = datetime.now(timezone.utc).isoformat()
        _write_receipt(path, {"application": application, "revision": declaration["revision"],
                              "state": "running", "started_at": started})
        try:
            result = invoke([declaration["runner"]], cwd=declaration["checkout"],
                            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": pwd.getpwuid(os.geteuid()).pw_dir},
                            timeout=1800, check=False)
            state = "succeeded" if result.returncode == 0 else "failed"
            exit_code = result.returncode
        except (OSError, subprocess.TimeoutExpired):
            state, exit_code = "failed", None
        receipt = {"application": application, "revision": declaration["revision"],
                   "state": state, "exit_code": exit_code,
                   "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat()}
        _write_receipt(path, receipt)
        return receipt
    finally:
        os.close(fd)



_REQUEST_ID = re.compile(r"[0-9a-f]{32}")


def _declaration_digest(declaration):
    return hashlib.sha256(json.dumps(declaration, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _request_path(request_id, state_dir):
    if type(request_id) is not str or not _REQUEST_ID.fullmatch(request_id):
        raise ValueError("invalid deployment request ID")
    return state_dir / ("request-" + request_id + ".json")


def _private_state(state_dir):
    _trusted(state_dir, directory=True)
    info = state_dir.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError("deployment state directory must be private")


def request_status(application, request_id, *, state_dir=STATE_DIR,
                   resolve=resolve_deployment, worker_claim=False):
    resolve(application)
    _private_state(state_dir)
    path = _request_path(request_id, state_dir)
    if path.is_symlink():
        raise PermissionError("symlink request receipt denied")
    if not path.exists():
        raise ValueError("deployment request not found")
    _trusted(path)
    if path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o077:
        raise PermissionError("untrusted request receipt")
    with path.open(encoding="utf-8") as stream:
        result = json.load(stream)
    if (type(result) is not dict or result.get("application") != application
            or result.get("request_id") != request_id
            or result.get("state") not in
            {"accepted", "running", "succeeded", "failed", "uncertain"}):
        raise PermissionError("deployment request binding mismatch")
    # A running receipt is historical state. The worker holds its dedicated
    # flock until it writes a terminal receipt; without that lock we have no
    # proof it is still alive (including after a host restart).
    # A newly accepted request may legitimately be waiting for the spawned worker.
    # After the bounded startup grace period, absence of the lock is uncertain.
    accepted_stale = False
    if result["state"] == "accepted" and not worker_claim:
        try:
            started = datetime.fromisoformat(result["started_at"])
            accepted_stale = (started.tzinfo is not None and
                              datetime.now(timezone.utc) - started > timedelta(seconds=30))
        except (KeyError, TypeError, ValueError):
            accepted_stale = True
    if result["state"] == "running" or accepted_stale:
        lock_path = state_dir / (".request-lock-" + path.stem)
        if lock_path.is_symlink():
            raise PermissionError("symlink worker lock denied")
        active = False
        if lock_path.exists():
            _trusted(lock_path)
            info = lock_path.stat()
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise PermissionError("untrusted worker lock")
            fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    active = True
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        if not active:
            result = {**result, "state": "uncertain", "recorded_state": result["state"]}
    return result


def accept(application, request_id, *, state_dir=STATE_DIR,
           resolve=resolve_deployment, spawn=subprocess.Popen):
    """Durably claim a request before launching a detached, unprivileged worker.

    No retry of an existing ID ever starts another process. An interrupted
    accepted/running request remains uncertain, not implicitly successful.
    """
    declaration = _eligible(application, resolve=resolve)
    _private_state(state_dir)
    path = _request_path(request_id, state_dir)
    if path.is_symlink():
        raise PermissionError("symlink request receipt denied")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        try:
            existing = request_status(application, request_id, state_dir=state_dir,
                                      resolve=resolve)
        except ValueError:
            # Another process may still be fsyncing its initial receipt.
            # Never interpret an incomplete durable claim as permission to retry.
            return {"application": application, "request_id": request_id,
                    "state": "uncertain"}
        if (existing.get("state") == "uncertain" and "revision" not in existing):
            return existing
        if (existing["revision"] != declaration["revision"] or
                existing.get("declaration_sha256") != _declaration_digest(declaration)):
            raise PermissionError("request bound to another deployment revision")
        return existing
    receipt = {"application": application, "request_id": request_id,
               "revision": declaration["revision"],
               "declaration_sha256": _declaration_digest(declaration),
               "state": "accepted",
               "started_at": datetime.now(timezone.utc).isoformat()}
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(receipt, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        dirfd = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except BaseException:
        # Fail closed: the claimed ID is never automatically dispatched again.
        raise
    try:
        spawn([sys.executable, "-m", "gway_remote.mcp_deployment_broker",
               "worker", application, request_id],
              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, close_fds=True,
              start_new_session=True,
              env={"PATH": "/usr/local/bin:/usr/bin:/bin",
                   "HOME": pwd.getpwuid(os.geteuid()).pw_dir})
    except OSError:
        receipt["state"] = "uncertain"
        _write_receipt(path, receipt)
    return receipt


def worker(application, request_id, *, state_dir=STATE_DIR,
           resolve=resolve_deployment):
    """Detached worker; never re-launches another request."""
    _private_state(state_dir)
    lock_path = state_dir / (".request-lock-" + _request_path(request_id, state_dir).stem)
    if lock_path.is_symlink():
        raise PermissionError("symlink worker lock denied")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077):
            raise PermissionError("untrusted worker lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = request_status(application, request_id, state_dir=state_dir,
                                 resolve=resolve, worker_claim=True)
        if receipt["state"] != "accepted":
            raise PermissionError("deployment worker already claimed")
        if receipt.get("declaration_sha256") != _declaration_digest(_eligible(application, resolve=resolve)):
            raise PermissionError("deployment declaration changed since acceptance")
        receipt["state"] = "running"
        _write_receipt(_request_path(request_id, state_dir), receipt)
        try:
            result = run(application, state_dir=state_dir, resolve=resolve)
            receipt["state"] = result["state"]
            receipt["exit_code"] = result["exit_code"]
        except (OSError, ValueError, PermissionError, RuntimeError, BlockingIOError):
            receipt["state"] = "failed"
            receipt["exit_code"] = None
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_receipt(_request_path(request_id, state_dir), receipt)
        return receipt
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preview", "status", "run", "worker"))
    parser.add_argument("application")
    parser.add_argument("request_id", nargs="?")
    args = parser.parse_args(argv)
    if args.action == "worker":
        if args.request_id is None:
            parser.error("worker requires request_id")
        result = worker(args.application, args.request_id)
    else:
        result = {"preview": preview, "status": status, "run": run}[args.action](args.application)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
