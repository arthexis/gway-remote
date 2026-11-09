"""Node-local deployment broker for root-provisioned MCP providers.

Only the operator-owned wrapper may invoke run; Watchtower must never supply
runner paths, arbitrary arguments, or environment variables.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import tempfile
from datetime import datetime, timezone

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
    if pwd.getpwuid(os.geteuid()).pw_name != deployment["run_as"]:
        raise PermissionError("deployment operator identity mismatch")
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
            "status": "declared", "execution": "node-owned-operator",
            "note": "read-only declaration; execution revalidates node-local state"}


def status(application, *, state_dir=STATE_DIR, resolve=resolve_deployment):
    resolve(application)
    path = _receipt_path(application, state_dir)
    if path.is_symlink():
        raise PermissionError("symlink receipt denied")
    if not path.exists():
        return {"application": application, "state": "never_run"}
    _trusted(path)
    return json.loads(path.read_text())


def run(application, *, state_dir=STATE_DIR, resolve=resolve_deployment, invoke=subprocess.run):
    declaration = _eligible(application, resolve=resolve)
    _trusted(state_dir, directory=True)
    lock_path = state_dir / LOCK_NAME
    if lock_path.is_symlink():
        raise PermissionError("symlink lock denied")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_uid != os.geteuid() or os.fstat(fd).st_mode & 0o022:
            raise PermissionError("untrusted lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Recheck after acquiring lock; a concurrent deployment may have
        # changed the checkout or installed declaration.
        if _eligible(application, resolve=resolve) != declaration:
            raise PermissionError("deployment declaration changed")
        path = _receipt_path(application, state_dir)
        previous = status(application, state_dir=state_dir, resolve=resolve)
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


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preview", "status", "run"))
    parser.add_argument("application")
    args = parser.parse_args(argv)
    result = {"preview": preview, "status": status, "run": run}[args.action](args.application)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
