#!/usr/bin/env python3
"""Fixed repository deployment through the existing gway-001 GitHub runner.

The owner-owned Aeon installer remains the only activation path. Never accept
a command, repository, host, checkout path or credential as caller input.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess
import tempfile

REPO = "arthexis/aeon-score"
ORIGIN = "https://github.com/arthexis/aeon-score.git"
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
MAX_BANK = 24 * 1024 * 1024

def checked_revision(value):
    if not isinstance(value, str) or not SHA.fullmatch(value) or value == "0" * 40:
        raise ValueError("Exact full Git SHA required")
    return value

def verify_main(response, revision):
    if response.get("commit", {}).get("sha") != revision:
        raise ValueError("Requested revision is not current Aeon main")

def verify_ci(response, revision):
    runs = response.get("workflow_runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("Exact main CI evidence unavailable")
    eligible = [r for r in runs if r.get("head_sha") == revision
                and r.get("head_branch") == "main" and r.get("event") == "push"
                and r.get("path", "").split("@")[0] == ".github/workflows/ci.yml"]
    if not eligible:
        raise ValueError("Exact main CI evidence unavailable")
    latest = max(eligible, key=lambda r: (r.get("run_number", 0), r.get("run_attempt", 0)))
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ValueError("Latest exact main CI not successful")

def validate_pin(pin):
    if pin.get("id") != "retro16-enhanced" or pin.get("status") != "approved":
        raise ValueError("Reviewed approved bank required")
    if not isinstance(pin.get("bank_sha256"), str) or not DIGEST.fullmatch(pin["bank_sha256"]):
        raise ValueError("Invalid bank digest")
    if type(pin.get("bank_bytes")) is not int or not 0 < pin["bank_bytes"] <= MAX_BANK:
        raise ValueError("Invalid bank size")
    for field in ("ci_run", "artifact_id"):
        if type(pin.get(field)) is not int or pin[field] <= 0:
            raise ValueError("Invalid CI artifact provenance")

def verify_bank(path, pin):
    if (path.resolve() != path or not path.is_file() or path.is_symlink()
            or path.stat().st_size != pin["bank_bytes"]):
        raise ValueError("Missing or unsafe pinned bank")
    with path.open("rb") as f:
        h = hashlib.sha256()
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    if h.hexdigest() != pin["bank_sha256"]:
        raise ValueError("Pinned bank digest mismatch")

def private_dir(path, uid):
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("Unsafe deployment directory")
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    if not path.is_dir() or info.st_uid != uid or info.st_mode & 0o077:
        raise PermissionError("Deployment directory is not private to owner")

def run():
    revision = checked_revision(os.environ["AEON_TARGET_SHA"])
    uid = os.geteuid()
    owner = pwd.getpwuid(uid)
    if uid == 0 or owner.pw_name != "arthe" or socket.gethostname().split(".")[0] != "gway-001":
        raise PermissionError("Existing gway-001 installation owner required")
    home = Path(owner.pw_dir)
    root = home / ".local/share/aeon-score"
    if not root.is_dir():
        raise ValueError("Existing Aeon Score installation required")
    os.umask(0o077)
    private_dir(root, uid)
    # Cross-repository reads use the existing owner gh configuration, never the
    # workflow GITHUB_TOKEN or a new secret. Do not print auth configuration.
    env = os.environ.copy()
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "PYTHONPATH", "GH_DEBUG", "GIT_TRACE", "GIT_CURL_VERBOSE"):
        env.pop(key, None)
    env.update(HOME=str(home), GIT_TERMINAL_PROMPT="0",
               XDG_RUNTIME_DIR=f"/run/user/{uid}",
               DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{uid}/bus")
    gh = str(home / ".local/bin/gh")
    if not Path(gh).is_file():
        gh = shutil.which("gh") or "gh"
    def api(path):
        return json.loads(subprocess.check_output([gh, "api", path], env=env))
    def git(path, *args):
        return subprocess.check_output(["git", "-C", str(path), *args], env=env, text=True).strip()
    def main_gate():
        verify_main(api(f"repos/{REPO}/branches/main"), revision)
        verify_ci(api(f"repos/{REPO}/actions/workflows/ci.yml/runs?head_sha={revision}&branch=main&event=push&per_page=30"), revision)
    with (root / "runner-deploy.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        main_gate()
        checkouts = root / "checkouts"
        private_dir(checkouts, uid)
        checkout = checkouts / revision
        if not checkout.exists():
            # Clone into a private temporary directory, then publish only a
            # complete detached checkout. Interrupted clones never become pins.
            with tempfile.TemporaryDirectory(prefix=".checkout-", dir=checkouts) as temp:
                staged = Path(temp) / "source"
                subprocess.run(["git", "clone", "--no-checkout", ORIGIN, str(staged)], env=env, check=True)
                git(staged, "checkout", "--detach", revision)
                if git(staged, "rev-parse", "HEAD") != revision:
                    raise ValueError("Checkout revision mismatch")
                staged.rename(checkout)
        private_dir(checkout, uid)
        if (git(checkout, "rev-parse", "HEAD") != revision
                or git(checkout, "rev-parse", "--abbrev-ref", "HEAD") != "HEAD"
                or git(checkout, "remote", "get-url", "origin") != ORIGIN
                or git(checkout, "status", "--porcelain", "--untracked-files=all")):
            raise ValueError("Unsafe or dirty pinned checkout")
        pin = json.loads((checkout / "instruments/retro16-enhanced.json").read_text())
        validate_pin(pin)
        # Verify the repo-owned source manifest/compiler pin before staging.
        subprocess.run(["/usr/bin/python3", "-B", "-c",
                        "from retro_runtime import pin; pin()"], cwd=checkout, env=env, check=True)
        staged = root / "staged"
        private_dir(staged, uid)
        stage_root = staged / "retro16"
        private_dir(stage_root, uid)
        bank_dir = stage_root / pin["bank_sha256"]
        private_dir(bank_dir, uid)
        bank = bank_dir / "retro16.sf2"
        if not bank.exists():
            run = api(f"repos/{REPO}/actions/runs/{pin['ci_run']}")
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                raise ValueError("Pinned bank CI not successful")
            artifact = api(f"repos/{REPO}/actions/artifacts/{pin['artifact_id']}")
            if (artifact.get("expired") or artifact.get("name") != "retro16-candidate"
                    or artifact.get("workflow_run", {}).get("id") != pin["ci_run"]):
                raise ValueError("Pinned artifact unavailable; rebuild and review")
            with tempfile.TemporaryDirectory(prefix=".bank-", dir=stage_root) as temp:
                subprocess.run([gh, "run", "download", str(pin["ci_run"]),
                                "-R", REPO, "-n", "retro16-candidate", "-D", temp],
                               env=env, check=True)
                source = Path(temp) / "candidate.sf2"
                verify_bank(source, pin)
                os.link(source, bank)
                bank.chmod(0o600)
        verify_bank(bank, pin)
        main_gate()
        # Do not run the broker before its initial owner-side declaration exists.
        # No shell substitutes, privilege changes, or generic remote exec.
        subprocess.run([str(checkout / "deploy.sh")], cwd=checkout, env=env, check=True)
        manifest = Path("/etc/gway-mcp-providers/aeon_score.json")
        if manifest.is_symlink() or manifest.stat().st_uid != 0 or manifest.stat().st_mode & 0o022:
            raise ValueError("Untrusted provider manifest")
        release = root / "releases" / revision
        executable = str(release / "mcp_provider.py")
        expected = {"source_id": "aeon_score", "revision": revision, "executable": executable,
                    "argv": [executable], "deployment": {"schema": 1, "checkout": str(checkout),
                    "runner": str(checkout / "deploy.sh"), "revision": revision}}
        if json.loads(manifest.read_text()) != expected:
            raise ValueError("Provider registration did not converge")
        verify_bank(root / "samples/retro16-enhanced" / pin["bank_sha256"] / "retro16.sf2", pin)
        unit = home / ".config/systemd/user/aeon-score-render@.service"
        if f"ExecStart=/usr/bin/python3 {release}/worker.py " not in unit.read_text():
            raise ValueError("Worker release did not converge")
        print(f"AEON_DEPLOYED revision={revision} bank_sha256={pin['bank_sha256']}")

if __name__ == "__main__":
    run()
