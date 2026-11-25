"""Fixed trusted Watchtower-local publishers. No public caller or bearer issuance."""
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing
import fcntl
import json
import os
import tempfile
from .activity_feed import EventConflict
from .activity_feed_maintenance import check_volume
from .activity_feed_hooks import deployment, observe_inventory, event
from .watchtower_deploy_notices import REPOSITORIES

_store = None
SOURCE = "/watchtower/internal"
PRINCIPAL = "watchtower-internal-v1"

def bind(store):
    global _store
    _store = store

def bound():
    return _store is not None

def ready(store):
    # One actual receiver-ready receipt; stable dedup across restarts.
    value = event(source=SOURCE, kind="feed.receiver_ready", identity="first-activation-v1",
                  at=datetime.now(timezone.utc).isoformat(), title="Activity Feed receiver ready",
                  summary="Dedicated persistent storage initialized", category="system", severity="success")
    try:
        store.append(value, producer=PRINCIPAL, allowed_source=SOURCE)
    except EventConflict:
        pass

def broker(application, node, attempt, state, at, sha):
    if not bound() or application not in REPOSITORIES:
        return False
    value = deployment(SOURCE, repository=REPOSITORIES[application], node=node,
                       attempt=attempt, state=state, at=at, sha=sha)
    _store.append(value, producer=PRINCIPAL, allowed_source=SOURCE)
    return True

def inventory(store, *, loader=None):
    if loader is None:
        from .node_registry_inventory import load
        loader = load
    from .activity_feed import _utc
    snapshot = loader()
    stamp = _utc(snapshot["generated_at"])
    root = store.path.parent
    checkpoint = root / "inventory-checkpoint.json"
    lock_path = root / "inventory.lock"
    with open(lock_path, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            old = json.loads(checkpoint.read_text()) if checkpoint.exists() else None
            if old and stamp <= old["stamp"]:
                return 0
            current, changes = observe_inventory(snapshot, old["state"] if old else None)
            for node, state in changes:
                value = event(source=SOURCE, kind="fleet."+state, identity=(node,stamp), at=stamp,
                    title="Node inventory: "+state.replace("_"," "), summary=node, category="fleet",
                    severity="warning" if state in ("contact_unknown","identity_unverified","registration_removed") else "info",
                    node=node)
                store.append(value, producer=PRINCIPAL, allowed_source=SOURCE)
            fd, name = tempfile.mkstemp(dir=root, prefix=".inventory-")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump({"stamp":stamp,"state":current},f,sort_keys=True)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(name, checkpoint)
            finally:
                Path(name).unlink(missing_ok=True)
            return len(changes)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
