"""Constrained local workload executor for the gway-remote runner."""
import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ALLOWED_REPOSITORY = "arthexis/ocpp-csms"
LCD_REPOSITORY = "arthexis/gway-lcd-sound"
SIM_REPOSITORY = "arthexis/ocpp-simulator"
TASKS = ("system-health", "ocpp-simulator", "lcd-sound-deploy", "ocpp-csms-deploy", "ocpp-simulator-deploy")


def validate(task: str, repository: str = "", sha: str = "") -> None:
    if task not in TASKS:
        raise ValueError("Unknown task")
    if task == "system-health":
        if repository or sha:
            raise ValueError("Health task takes no repository or sha")
        return
    expected = (LCD_REPOSITORY if task == "lcd-sound-deploy" else
                SIM_REPOSITORY if task == "ocpp-simulator-deploy" else ALLOWED_REPOSITORY)
    if repository != expected:
        raise ValueError("Repository not allowed")
    if len(sha) != 40 or not all(c in "0123456789abcdefABCDEF" for c in sha):
        raise ValueError("A 40-character commit SHA is required")


def run(task: str, repository: str = "", sha: str = "") -> None:
    validate(task, repository, sha)
    if task == "system-health":
        print(json.dumps({
            "node": platform.node(),
            "machine": platform.machine(),
            "system": platform.system(),
            "python": platform.python_version(),
        }, sort_keys=True))
        return

    if task in ("lcd-sound-deploy", "ocpp-csms-deploy", "ocpp-simulator-deploy"):
        from .best_effort import manual_execute
        from .github_state import GitHub
        installer = {
            "lcd-sound-deploy": deploy_lcd_sound,
            "ocpp-csms-deploy": deploy_csms,
            "ocpp-simulator-deploy": deploy_simulator,
        }[task]
        name = {"lcd-sound-deploy": "gway-lcd-sound",
                "ocpp-csms-deploy": "ocpp-csms",
                "ocpp-simulator-deploy": "ocpp-simulator"}[task]
        print(json.dumps(manual_execute(GitHub(), name, sha, installer), sort_keys=True))
        return

    # Disposable workspace, no modification to ~/Repos or production services.
    with tempfile.TemporaryDirectory(prefix="gway-remote-") as directory:
        worktree = Path(directory) / "source"
        subprocess.run(["git", "clone", "--quiet", "--no-checkout",
                        "https://github.com/arthexis/ocpp-csms.git", str(worktree)],
                       check=True, timeout=180)
        subprocess.run(["git", "-C", str(worktree), "checkout", "--detach", sha],
                       check=True, timeout=60)
        subprocess.run([sys.executable, "-m", "venv", str(Path(directory) / "venv")],
                       check=True, timeout=90)
        python = str(Path(directory) / "venv" / "bin" / "python")
        subprocess.run([python, "-m", "pip", "install", ".[dev]"],
                       cwd=worktree, check=True, timeout=360)
        subprocess.run([python, "scripts/pr_simulator_smoke.py"],
                       cwd=worktree, check=True, timeout=120)


def deploy_simulator(sha: str) -> None:
    """Install the approved simulator CLI persistently; never start a session or service."""
    with tempfile.TemporaryDirectory(prefix="simulator-deploy-") as directory:
        source = Path(directory) / "source"
        subprocess.run(["git", "clone", "--quiet", "--no-checkout",
                        "https://github.com/arthexis/ocpp-simulator.git", str(source)],
                       check=True, timeout=180)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", sha],
                       check=True, timeout=60)
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                         text=True, timeout=20).strip()
        if actual.lower() != sha.lower():
            raise ValueError("Simulator checkout SHA mismatch")
        subprocess.run(["sh", "./deploy.sh"], cwd=source, check=True, timeout=600)
        subprocess.run([str(Path.home() / ".local/bin/ocpp-simulator"), "--help"],
                       check=True, timeout=30)


def deploy_csms(sha: str) -> None:
    """Persistently deploy the approved CSMS main commit via its canonical Ansible wrapper.

    Unlike PR simulator smoke tests, this intentionally updates the appliance.
    The upstream deployer owns incumbent traffic detection and cutover.
    """
    with tempfile.TemporaryDirectory(prefix="csms-deploy-") as directory:
        source = Path(directory) / "source"
        subprocess.run(["git", "clone", "--quiet", "--no-checkout",
                        "https://github.com/arthexis/ocpp-csms.git", str(source)],
                       check=True, timeout=180)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", sha],
                       check=True, timeout=60)
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                         text=True, timeout=20).strip()
        if actual.lower() != sha.lower():
            raise ValueError("Checkout SHA mismatch")
        # Never bypass the canonical deployment safety checks or invoke as root.
        subprocess.run(["sh", "./deploy.sh"], cwd=source, check=True, timeout=900)


def user_systemd_env() -> dict[str, str]:
    """Locate the persistent user's systemd bus in a non-login runner service."""
    runtime = Path(f"/run/user/{os.getuid()}")
    bus = runtime / "bus"
    if not bus.is_socket():
        raise RuntimeError(f"User systemd bus unavailable: {bus}")
    return {**os.environ, "XDG_RUNTIME_DIR": str(runtime),
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={bus}"}


def deploy_lcd_sound(sha: str) -> None:
    """Deploy only the server-authorized main SHA, never untrusted PR code.

    Keep the existing observer in shadow mode; do not enable or start it.
    """
    with tempfile.TemporaryDirectory(prefix="lcd-sound-deploy-") as directory:
        source = Path(directory) / "source"
        subprocess.run(["git", "clone", "--quiet", "--no-checkout",
                        "https://github.com/arthexis/gway-lcd-sound.git", str(source)],
                       check=True, timeout=180)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", sha],
                       check=True, timeout=60)
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                         text=True, timeout=20).strip()
        if actual.lower() != sha.lower():
            raise ValueError("Checkout SHA mismatch")
        unit = source / "scripts/deploy/systemd/user/gway-app-observer.service"
        if unit.exists() and (
            "ExecStart=%h/.local/bin/gway-app-observer --notification-mode shadow --no-processes"
            not in unit.read_text(encoding="utf-8")
        ):
            raise ValueError("LCD Sound observer unit must remain shadow-only")
        env = {**os.environ, "PYTHONPATH": str(source / "scripts/gway")}
        subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/"],
                       cwd=source, env=env, check=True, timeout=300)
        subprocess.run(["bash", "scripts/deploy/install.sh", "install", "--no-restart"],
                       cwd=source, check=True, timeout=120)
        subprocess.run(["bash", "scripts/deploy/install.sh", "verify"],
                       cwd=source, check=True, timeout=60)
        # Never switch modes; the installed service definition is shadow-only.
        subprocess.run(["systemctl", "--user", "daemon-reload"],
                       env=user_systemd_env(), check=True, timeout=20)
        subprocess.run(["systemctl", "--user", "try-restart", "gway-app-observer.service"],
                       env=user_systemd_env(), check=True, timeout=30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an approved gway-001 workload")
    subparsers = parser.add_subparsers(dest="command", required=True)
    execute = subparsers.add_parser("run")
    execute.add_argument("task", choices=TASKS)
    execute.add_argument("--repository", default="")
    execute.add_argument("--sha", default="")
    inspection = subparsers.add_parser("reconcile", help="Read-only appliance deployment report")
    inspection.add_argument("--dry-run", action="store_true", help="Do not deploy (always read-only)")
    status_parser = subparsers.add_parser("status", help="Inspect local attempts and health")
    status_parser.add_argument("--json", action="store_true")
    subparsers.add_parser("probe-csms", help="Read-only CSMS health diagnosis")
    logs_parser = subparsers.add_parser("logs", help="Inspect local installation logs")
    logs_parser.add_argument("component", nargs="?", choices=("ocpp-csms", "ocpp-simulator", "gway-lcd-sound"))
    logs_parser.add_argument("--lines", type=int, default=None)
    report_parser = subparsers.add_parser("report-bundle", help="Export sanitized artifact report")
    report_parser.add_argument("--output", required=True)
    subparsers.add_parser("deploy-batch", help="Run eligible merged revisions once (explicit invocation)")
    args = parser.parse_args()
    if args.command == "probe-csms":
        from .csms_health import csms_probe
        print(json.dumps(csms_probe(), indent=2, sort_keys=True))
        return
    if args.command == "logs":
        from .logs import list_logs, read_log
        try:
            if args.lines is None and args.component is None:
                for item in list_logs():
                    print(item.name)
            else:
                content = read_log(name=args.component, lines=args.lines or 100)
                if content is None:
                    parser.exit(1, "gway-remote: no installation logs found\\n")
                print(content)
        except (OSError, ValueError) as exc:
            parser.exit(1, f"gway-remote: {exc}\\n")
        return
    if args.command == "report-bundle":
        from .report_bundle import bundle
        try:
            print(bundle(args.output))
        except (OSError, ValueError) as exc:
            parser.exit(1, f"gway-remote: report unavailable: {exc}\\n")
        return
    if args.command == "status":
        from .status import status, format_status
        result = status()
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else format_status(result))
        return
    if args.command == "reconcile":
        from .github_state import GitHub, report
        from .attempts import attempted_shas
        try:
            print(json.dumps(report(GitHub(), attempts=attempted_shas()), indent=2, sort_keys=True))
        except Exception as exc:
            parser.exit(1, f"gway-remote: reconciliation unavailable: {exc}\n")
        return
    if args.command == "deploy-batch":
        from datetime import datetime, timezone
        from .best_effort import execute
        from .github_state import GitHub
        try:
            result = execute(GitHub(), datetime.now(timezone.utc), {
                "ocpp-csms": deploy_csms,
                "ocpp-simulator": deploy_simulator,
                "gway-lcd-sound": deploy_lcd_sound,
            })
            print(json.dumps(result, indent=2, sort_keys=True))
            if any(item["status"] == "failed" for item in result["results"]):
                parser.exit(1, "gway-remote: one or more installations failed\\n")
        except (ValueError, RuntimeError, OSError) as exc:
            parser.exit(1, f"gway-remote: {exc}\\n")
        return
    if args.command == "run":
        try:
            run(args.task, args.repository, args.sha)
        except (ValueError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            parser.exit(1, f"gway-remote: {exc}\n")


if __name__ == "__main__":
    main()
