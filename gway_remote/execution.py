"""Sequential deployment orchestration with explicit callbacks."""
from contextlib import contextmanager
import fcntl
from pathlib import Path
from .reconcile import Decision, reconcile

@contextmanager
def appliance_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("appliance deployment already active") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

def execute(client, collect, clock, deploy, verify, record, lock_path):
    """Callbacks supply side effects; no automatic deployment entry point."""
    with appliance_lock(lock_path):
        plan = reconcile(collect(client), clock())
        if plan.decision != Decision.READY:
            return plan
        snapshot = plan.desired_revisions
        for target in plan.targets:
            fresh = reconcile(collect(client), clock())
            if fresh.decision != Decision.READY or fresh.desired_revisions != snapshot:
                raise RuntimeError("deployment snapshot became stale")
            if target not in fresh.targets:
                raise RuntimeError("target no longer pending")
            deploy(target.name, target.sha)
            if verify(target.name, target.sha) is not True:
                raise RuntimeError("installation verification failed: " + target.name)
            record(target.name, target.sha)
        return plan
