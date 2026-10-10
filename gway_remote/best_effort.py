"""Best-effort sequential installer with shared appliance lock."""
from contextlib import contextmanager
import fcntl
from pathlib import Path

from .attempt_policy import plan
from .attempts import DEFAULT_DIR, attempted_shas, mark
from .github_state import collect, main_head
from .logs import capture_log, log_filename
from .reconcile import TARGETS

LOCK_PATH = DEFAULT_DIR / "appliance.lock"
INSTALLERS = {
    "ocpp-csms": "deploy_csms",
    "ocpp-simulator": "deploy_simulator",
    "gway-lcd-sound": "deploy_lcd_sound",
}


@contextmanager
def appliance_lock(path=LOCK_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("appliance deployment already active") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def execute(client, now, installers, directory=DEFAULT_DIR, lock_path=None):
    """Call only under a trusted runner. Installer errors are recorded and isolated.

    Re-check all main heads before each component. A changing head aborts the
    remaining batch rather than deploying a stale revision.
    """
    directory = Path(directory)
    with appliance_lock(lock_path or directory / "appliance.lock"):
        snapshot = collect(client, attempted_shas(directory))
        decision = plan(snapshot, now)
        if decision.state != "ready":
            return {"decision": decision.state, "reason": decision.reason, "results": []}
        results = []
        for name, sha in decision.pending:
            if any(main_head(client, repo).lower() != state.sha.lower()
                   for state, (_, repo) in zip(snapshot, TARGETS)):
                return {"decision": "stale", "reason": "main revision changed",
                        "results": results}
            filename = log_filename(name, sha)
            # Persist before running; an interrupted attempt is never auto-retried.
            mark(name, sha, "started", directory, log=filename)
            try:
                with capture_log(directory, filename):
                    installers[name](sha)
            except Exception as exc:
                mark(name, sha, "failed", directory, error=exc, log=filename)
                results.append({"name": name, "sha": sha, "status": "failed",
                                "log": filename, "error": str(exc)[:500]})
            else:
                mark(name, sha, "installed", directory, log=filename)
                results.append({"name": name, "sha": sha, "status": "installed",
                                "log": filename})
        return {"decision": "completed", "results": results}
