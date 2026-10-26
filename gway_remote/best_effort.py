"""Best-effort sequential installer with shared appliance lock."""
from contextlib import contextmanager
import fcntl
from pathlib import Path

from .attempt_policy import plan
from .attempts import DEFAULT_DIR, attempted_shas, read_attempts, mark
from .github_state import collect, main_head, ci_for_head
from .logs import capture_log, log_filename, read_log
from .reconcile import TARGETS

LOCK_PATH = DEFAULT_DIR / "appliance.lock"
INSTALLERS = {
    "ocpp-csms": "deploy_csms",
    "ocpp-reports": "deploy_reports",
    "ocpp-simulator": "deploy_simulator",
    "gway-lcd-sound": "deploy_lcd_sound",
    "gway-agent-ops": "deploy_agent_ops",
    "gway-ap-kiosk": "deploy_ap_kiosk",
    "gway-rfid": "deploy_rfid",
    "gway-bastion": "deploy_bastion",
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


def execute(client, now, installers, directory=DEFAULT_DIR, lock_path=None, *, bypass_quiet=False, retry_failed=False, verify=None, deploy_all=False, target=None):
    """Call only under a trusted runner. Installer errors are recorded and isolated.

    Re-check all main heads before each component. A changing head aborts the
    remaining batch rather than deploying a stale revision.
    """
    if target is not None and target not in dict(TARGETS):
        raise ValueError("unknown deployment target")
    if target is not None and not deploy_all:
        raise ValueError("target selection requires explicit --all")
    from .deployment_policy import require_local_deployment
    require_local_deployment(target)
    directory = Path(directory)
    with appliance_lock(lock_path or directory / "appliance.lock"):
        if deploy_all:
            # Explicit --all bypasses the quiet period, never main-branch CI.
            snapshot = tuple((name, repo, main_head(client, repo)) for name, repo in TARGETS
                             if target is None or name == target)
            results = []
            for name, repo, sha in snapshot:
                try:
                    ci = ci_for_head(client, repo, sha)
                    if ci != "success":
                        results.append({"name": name, "sha": sha, "status": "blocked",
                                        "reason": f"merged PR CI {ci}; successful merged PR CI required"})
                        continue
                    if main_head(client, repo).lower() != sha.lower():
                        results.append({"name": name, "sha": sha, "status": "blocked",
                                        "reason": "main SHA changed during deployment"})
                        continue
                    filename = log_filename(name, sha)
                    mark(name, sha, "started", directory, log=filename)
                    try:
                        with capture_log(directory, filename):
                            installers[name](sha)
                            if verify is not None:
                                verify(name, sha)
                    except Exception as exc:
                        mark(name, sha, "failed", directory, error=exc, log=filename)
                        tail = read_log(directory, name=name, lines=40)
                        if tail:
                            print(f"Installer failure tail for {name} ({filename}):\n{tail}", flush=True)
                        results.append({"name": name, "sha": sha, "status": "failed",
                                        "log": filename, "reason": str(exc)[:500]})
                        continue
                    outcome = "staged" if name == "gway-bastion" else "installed"
                    mark(name, sha, outcome, directory, log=filename)
                    results.append({"name": name, "sha": sha, "status": outcome, "log": filename})
                except Exception as exc:
                    results.append({"name": name, "sha": sha, "status": "blocked",
                                    "reason": f"preflight unavailable: {str(exc)[:400]}"})
            unsuccessful = [row for row in results if row["status"] not in ("installed", "staged")]
            return {"decision": "partial" if unsuccessful else "completed",
                    "reason": (f"{len(unsuccessful)} of {len(results)} repositories not deployed"
                               if unsuccessful else "all selected repositories deployed"),
                    "results": results}
        attempted = attempted_shas(directory)
        if retry_failed:
            if not bypass_quiet:
                raise ValueError('failed retry requires explicit manual --now')
            for name, entry in read_attempts(directory).items():
                if entry.get('status') == 'failed':
                    attempted.pop(name, None)
        snapshot = collect(client, attempted)
        decision = plan(snapshot, now, bypass_quiet=bypass_quiet)
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
                    if verify is not None:
                        verify(name, sha)
            except Exception as exc:
                mark(name, sha, "failed", directory, error=exc, log=filename)
                results.append({"name": name, "sha": sha, "status": "failed",
                                "log": filename, "error": str(exc)[:500]})
                break
            else:
                mark(name, sha, "installed", directory, log=filename)
                results.append({"name": name, "sha": sha, "status": "installed",
                                "log": filename})
        return {"decision": "completed", "results": results}

def manual_execute(client, name, sha, installer, directory=DEFAULT_DIR):
    """Explicit owner deployment: bypass quiet period, not SHA/CI/lock safety.

    Share the automatic attempt journal so a successful manual install is not
    installed again by the scheduled queue. Failed manual attempts also remain
    one-shot until a new SHA arrives.
    """
    from .github_state import ci_for_head
    from .reconcile import _SHA
    if name not in INSTALLERS or not _SHA.fullmatch(sha):
        raise ValueError("invalid manual deployment target")
    from .deployment_policy import require_local_deployment
    require_local_deployment(name)
    directory = Path(directory)
    with appliance_lock(directory / "appliance.lock"):
        repo = dict(TARGETS)[name]
        if main_head(client, repo).lower() != sha.lower():
            raise ValueError("manual SHA must match current main head")
        if ci_for_head(client, repo, sha) != "success":
            raise ValueError("manual SHA requires successful main CI")
        if attempted_shas(directory).get(name, "").lower() == sha.lower():
            return {"decision": "idle", "reason": "SHA already attempted"}
        filename = log_filename(name, sha)
        mark(name, sha, "started", directory, log=filename)
        try:
            with capture_log(directory, filename):
                installer(sha)
        except Exception as exc:
            mark(name, sha, "failed", directory, error=exc, log=filename)
            raise
        outcome = "staged" if name == "gway-bastion" else "installed"
        mark(name, sha, outcome, directory, log=filename)
        return {"decision": "completed", "name": name, "sha": sha, "status": outcome}
