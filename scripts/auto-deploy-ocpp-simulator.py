#!/usr/bin/env python3
"""CI-gated, repository-fixed simulator deployment on GWay Remote's existing runner.

No user-selected repository, revision, URL, host, shell or service actions.
A PR Draft, missing main push CI or failed verification cannot admit a deploy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import time

REPOSITORY = "arthexis/ocpp-simulator"
CLONE_URL = "https://github.com/arthexis/ocpp-simulator.git"
PR_NUMBER = 20
SHA = re.compile(r"[0-9a-f]{40}\Z")
MODULE = "github.com/lorenzodonini/ocpp-go"
MODULE_VERSION = "v0.19.0"
MODULE_SUM = "h1:THNriVV3bUWkGzaIkDeytcgoeBRjoN9ezPHsddIDfgc="


class AdmissionError(RuntimeError):
    pass


# Fixed labels only. Never derive diagnostics from command arguments or exceptions.
_STAGE = "preflight"
_STARTED_NS = 0
_STAGES = frozenset({
    "preflight", "github_admission", "release_inspection", "checkout",
    "ansible_install", "release_verify", "go_provenance", "final_sha_fence",
})


def stage(name: str) -> None:
    global _STAGE, _STARTED_NS
    if name not in _STAGES:
        raise ValueError("invalid internal stage")
    _STAGE = name
    _STARTED_NS = time.monotonic_ns()



# Frozen, literal task names from the approved ocpp-simulator release role
# (revision 67e2d0e0fef704d7c693a6bd86af29bcc60db9a5).
# No arbitrary task names, log lines or command fields can appear in receipts.
_SAFE_ANSIBLE_TASKS = frozenset({
    "Validate deployment user and supported Python",
    "Identify complete checkout revision",
    "Validate immutable revision identifier",
    "Capture optional expected main SHA from automatic deployment",
    "Fail closed on malformed or mismatched expected main SHA",
    "Select immutable release paths",
    "Create simulator installation directories",
    "Inspect immutable release directory",
    "Verify existing release provenance and installation",
    "Verify existing release executable",
    "Inspect Go executable in immutable release",
    "Reject existing release lacking Go executable",
    "Inspect isolated LAB-6 client in immutable release",
    "Reject existing release missing isolated LAB-6 client",
    "Reject incomplete immutable release without modifying it",
    "Create versioned virtual environment",
    "Install requested checkout into versioned release",
    "Stage Go sources without modifying the Git checkout",
    "Resolve Go module checksums in staged source",
    "Inspect pinned ocpp-go module in staged source",
    "Reject unpinned ocpp-go module",
    "Verify staged Go module integrity",
    "Build pinned Go backend into candidate release",
    "Build isolated LAB-6 client into the same candidate release",
    "Calculate relative checksum of isolated LAB-6 client",
    "Store isolated LAB-6 client checksum in immutable release",
    "Verify isolated LAB-6 client checksum before activation",
    "Verify Go backend",
    "Record release provenance",
    "Verify candidate release before activation",
    "Inspect existing current release link",
    "Refuse unsafe current release path",
    "Read currently active release target",
    "Determine whether activation is necessary",
    "Inspect existing previous release pointer",
    "Refuse unmanaged previous release path",
    "Reject superseded main immediately before mutating release pointers",
    "Preserve previous release before changing current",
    "Activate requested revision",
    "Expose CLI in user bin directory",
    "Expose Go backend CLI in user bin directory",
    "Expose explicit Python backend CLI",
    "Verify active command",
    "Verify explicit Python CLI",
    "Verify Go backend dispatch",
})
_TASK_HEADER = re.compile(r"TASK \[([^\]\r\n]{1,180})\] \*{3,}\Z")
_FATAL_HEADER = re.compile(r"fatal: \[[^\]\r\n]{1,150}\]: FAILED!(?:\s+=>.*)?\Z")
_FAILED_RECAP = re.compile(r"\bfailed=[1-9][0-9]*\b")


def ansible_failed_task(exc: BaseException) -> str:
    """Return an allowlisted task only with fatal marker and failed PLAY RECAP."""
    if not isinstance(exc, subprocess.CalledProcessError) or _STAGE != "ansible_install":
        return "unknown"
    output = exc.output
    if not isinstance(output, str):
        return "unknown"
    task = None
    fatal_task = None
    in_recap = False
    recap_failed = False
    for line in output[-262144:].splitlines():
        if len(line) > 4096:
            continue
        match = _TASK_HEADER.fullmatch(line)
        if match:
            task = match.group(1) if match.group(1) in _SAFE_ANSIBLE_TASKS else None
            in_recap = False
        elif _FATAL_HEADER.fullmatch(line) and task is not None:
            fatal_task = task
        elif line.startswith("PLAY RECAP ") and set(line[11:]).issubset({" ", "*"}):
            in_recap = True
        elif in_recap and _FAILED_RECAP.search(line):
            recap_failed = True
    return fatal_task if recap_failed and fatal_task is not None else "unknown"


def safe_failure(exc: BaseException) -> str:
    # No str(exc), traceback, argv, cwd, stdout, stderr or environment.
    kind = type(exc).__name__
    if kind not in {
        "AdmissionError", "CalledProcessError", "TimeoutExpired",
        "OSError", "ValueError", "JSONDecodeError", "SubprocessError",
    }:
        kind = "Other"
    code = exc.returncode if isinstance(exc, subprocess.CalledProcessError) else None
    exit_code = str(code) if type(code) is int else "none"
    elapsed = max(0, (time.monotonic_ns() - _STARTED_NS) // 1_000_000)
    task_receipt = (
        f' ansible_task="{ansible_failed_task(exc)}"' if _STAGE == "ansible_install" else ""
    )
    return (
        "::error::simulator auto-install failed closed "
        f"stage={_STAGE} kind={kind} exit_code={exit_code} elapsed_ms={elapsed}"
        f"{task_receipt}"
    )


def require_sha(value: object) -> str:
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise AdmissionError("invalid 40-character commit SHA")
    return value


def invoke(argv: list[str], *, cwd: Path | None = None,
           env: dict[str, str] | None = None, timeout: int = 30) -> str:
    result = subprocess.run(
        argv, cwd=cwd, env=env, check=True,
        capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout.strip()


def github(endpoint: str) -> dict:
    # Fixed paths assembled only from an independently verified SHA.
    reply = invoke(["gh", "api", endpoint], timeout=25)
    result = json.loads(reply)
    if not isinstance(result, dict):
        raise AdmissionError("GitHub response is not an object")
    return result


def verified_ci(data: dict, sha: str) -> bool:
    require_sha(sha)
    runs = data.get("workflow_runs")
    if not isinstance(runs, list):
        raise AdmissionError("missing simulator push CI run list")
    matching = [
        r for r in runs
        if isinstance(r, dict)
        and r.get("head_sha") == sha
        and r.get("event") == "push"
        and r.get("head_branch") == "main"
        and isinstance(r.get("run_number"), int)
        and isinstance(r.get("run_attempt"), int)
    ]
    if not matching:
        return False
    most_recent = max(matching, key=lambda r: (r["run_number"], r["run_attempt"]))
    return most_recent.get("status") == "completed" and most_recent.get("conclusion") == "success"


def main_sha() -> str:
    branch = github(f"repos/{REPOSITORY}/branches/main")
    commit = branch.get("commit")
    if not isinstance(commit, dict):
        raise AdmissionError("simulator main commit missing")
    return require_sha(commit.get("sha"))


def read_pointer(path: Path) -> str:
    if path.is_symlink():
        return os.readlink(path)
    if path.exists():
        raise AdmissionError("unmanaged non-symlink release pointer")
    return ""


def preflight() -> None:
    if os.geteuid() == 0 or pwd.getpwuid(os.geteuid()).pw_name != "arthe":
        raise AdmissionError("deploy runner must be non-root operator arthe")
    if platform.machine() != "aarch64":
        raise AdmissionError("deploy runner must be native ARM64")
    for cmd in ("gh", "git", "python3", "go", "ansible-playbook", "flock"):
        if shutil.which(cmd) is None:
            raise AdmissionError("required existing deploy tool is unavailable")


def verify_installed(source: Path, release_root: Path, user_bin: Path, sha: str,
                     before_current: str, before_previous: str) -> None:
    verifier = source / "scripts" / "verify_main_install.py"
    if not verifier.is_file():
        raise AdmissionError("simulator release verifier unavailable")
    invoke(
        [sys.executable, str(verifier),
         "--root", str(release_root), "--bin-dir", str(user_bin),
         "--expected-sha", sha, "--before-current", before_current,
         "--before-previous", before_previous],
        cwd=source, timeout=30,
    )
    stage("go_provenance")
    # A checksum alone doesn't prove Go dependency provenance.
    lab_bin = release_root / "current" / "bin" / "r6c3b2-uidlab"
    metadata = invoke(["go", "version", "-m", str(lab_bin)], timeout=20)
    if not any(
        line.split()[:3] == ["dep", MODULE, MODULE_VERSION]
        and MODULE_SUM in line
        for line in metadata.splitlines()
    ):
        raise AdmissionError("installed test-only client lacks pinned Go provenance")


def auto_install() -> str:
    stage("preflight")
    preflight()
    stage("github_admission")
    # This opt-in gate prevents deploying the previously installed old main
    # when the GWay Remote integration merges before simulator PR #20.
    pr = github(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}")
    if pr.get("merged") is not True:
        return "SKIPPED: simulator PR #20 remains unmerged"
    sha = main_sha()
    ci = github(
        f"repos/{REPOSITORY}/actions/workflows/ci.yml/runs?"
        f"head_sha={sha}&event=push&per_page=100"
    )
    if not verified_ci(ci, sha):
        return "SKIPPED: exact current simulator main push CI is not successful"

    stage("release_inspection")
    root = Path.home() / ".local" / "share" / "ocpp-simulator"
    user_bin = Path.home() / ".local" / "bin"
    # Reject unmanaged symlink layout before creating any source checkout.
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise AdmissionError("unmanaged simulator release root")
    old_current = read_pointer(root / "current")
    old_previous = read_pointer(root / "previous")
    destination = str(root / "releases" / sha)

    # No writes to the existing ~/Repos/ocpp-simulator operator checkout.
    stage("checkout")
    with tempfile.TemporaryDirectory(prefix="ocpp-sim-verified-") as tmp:
        source = Path(tmp) / "source"
        git_env = os.environ.copy()
        git_env.update({
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        })
        invoke([
            "git", "-c", "credential.helper=!gh auth git-credential",
            "-c", f"core.hooksPath={os.devnull}",
            "clone", "--quiet", "--single-branch", "--branch", "main",
            "--no-checkout", CLONE_URL, str(source),
        ], env=git_env, timeout=120)
        cloned_sha = require_sha(
            invoke(["git", "-C", str(source), "rev-parse", "refs/remotes/origin/main"])
        )
        if cloned_sha != sha:
            return "SKIPPED: simulator main moved during clean checkout"
        invoke(["git", "-C", str(source), "-c", f"core.hooksPath={os.devnull}",
                "checkout", "--quiet", "--detach", sha],
               env=git_env, timeout=30)
        if require_sha(invoke(["git", "-C", str(source), "rev-parse", "HEAD"])) != sha:
            raise AdmissionError("simulator checkout identity mismatch")
        for path in (
            "scripts/verify_main_head.py", "scripts/verify_main_install.py",
            "ansible/roles/ocpp_simulator/tasks/main.yml", "deploy.sh",
        ):
            if not (source / path).is_file():
                raise AdmissionError("simulator approved installation contract absent")
        if main_sha() != sha:
            return "SKIPPED: simulator main superseded before installation"

        if old_current == destination:
            stage("release_verify")
            verify_installed(source, root, user_bin, sha, old_current, old_previous)
            stage("final_sha_fence")
            if main_sha() != sha:
                raise AdmissionError("main advanced while verifying installed release")
            return f"UP_TO_DATE: verified installed simulator {sha}"

        env = os.environ.copy()
        env["OCPP_SIMULATOR_EXPECTED_MAIN_SHA"] = sha
        # The same gh authentication is inherited by the Ansible fence; no
        # runner re-registration, sudo, new credential or node executor.
        stage("ansible_install")
        invoke(["sh", "./deploy.sh"], cwd=source, env=env, timeout=2400)
        stage("release_verify")
        verify_installed(source, root, user_bin, sha, old_current, old_previous)
        stage("final_sha_fence")
        if main_sha() != sha:
            raise AdmissionError("main advanced during installation; installed receipt not accepted")
        return f"INSTALLED: verified simulator {sha} (no simulator session started)"


def main() -> int:
    try:
        result = auto_install()
    except (AdmissionError, OSError, ValueError, json.JSONDecodeError,
            subprocess.SubprocessError) as exc:
        # No shell output or auth details: never leak GitHub credentials.
        print(safe_failure(exc))
        return 1
    print(f"::notice::{result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
