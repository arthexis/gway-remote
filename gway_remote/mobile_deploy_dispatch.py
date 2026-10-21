"""Explicit manual GitHub Actions dispatch, with durable uncertainty."""
import fcntl
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from .attempts import DEFAULT_DIR
from .mobile_deployments import validate_selection

JOURNAL = DEFAULT_DIR / "mobile-deploy-dispatch.json"
LOCK = DEFAULT_DIR / "mobile-deploy-dispatch.lock"
IDENTIFIER = re.compile(r"^[0-9a-f]{32}$")

def send(target, request_id):
    token = os.getenv("GWAY_REMOTE_DISPATCH_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        raise RuntimeError("deployment_token_unavailable")
    request = Request(
        "https://api.github.com/repos/arthexis/gway-remote/actions/workflows/appliance-deploy.yml/dispatches",
        data=json.dumps({"ref": "main", "inputs": {"repository": target, "request_id": request_id}}).encode(),
        method="POST", headers={"Authorization": "Bearer " + token,
                                "Accept": "application/vnd.github+json",
                                "Content-Type": "application/json"})
    with urlopen(request, timeout=15) as response:
        if response.status != 204:
            raise RuntimeError("deployment_dispatch_unconfirmed")

def dispatch(arguments, *, sender=send, journal=JOURNAL, lock=LOCK):
    if type(arguments) is not dict or set(arguments) != {"target", "request_id", "confirm"}:
        raise ValueError("invalid_deployment_arguments")
    target = validate_selection({"target": arguments["target"]})["target"]
    request_id = arguments["request_id"]
    if type(request_id) is not str or not IDENTIFIER.fullmatch(request_id):
        raise ValueError("invalid_deployment_request_id")
    if arguments["confirm"] is not True:
        raise ValueError("deployment_confirmation_required")
    journal, lock = Path(journal), Path(lock)
    journal.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if journal.is_symlink() or lock.is_symlink():
        raise RuntimeError("unsafe_dispatch_journal")
    with open(lock, "a+", encoding="utf-8") as guard:
        os.fchmod(guard.fileno(), 0o600)
        fcntl.flock(guard, fcntl.LOCK_EX)
        records = json.loads(journal.read_text()) if journal.exists() else {}
        if type(records) is not dict:
            raise RuntimeError("invalid_dispatch_journal")
        if request_id in records:
            if records[request_id]["target"] != target:
                raise ValueError("deployment_request_id_conflict")
            return records[request_id]
        if any(row.get("state") == "unconfirmed" for row in records.values()):
            raise ValueError("deployment_dispatch_unresolved")
        record = {"schema": 1, "request_id": request_id, "target": target,
                  "state": "unconfirmed", "run_id": None,
                  "requested_at": datetime.now(timezone.utc).isoformat()}
        records[request_id] = record
        fd, name = tempfile.mkstemp(prefix=".dispatch-", dir=journal.parent)
        try:
            with os.fdopen(fd, "w") as output:
                os.fchmod(output.fileno(), 0o600)
                json.dump(records, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, journal)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        sender(target, request_id)
        return record
