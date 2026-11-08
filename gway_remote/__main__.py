"""Constrained local workload executor for the gway-remote runner."""
import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from .reconcile import TARGETS as DEPLOYMENT_TARGETS

ALLOWED_REPOSITORY = "arthexis/ocpp-csms"
REPORTS_REPOSITORY = "arthexis/ocpp-reports"
LCD_REPOSITORY = "arthexis/gway-lcd-sound"
AGENT_REPOSITORY = "arthexis/gway-agent-ops"
KIOSK_REPOSITORY = "arthexis/gway-ap-kiosk"
RFID_REPOSITORY = "arthexis/gway-rfid"
BASTION_REPOSITORY = "arthexis/gway-bastion"
TASKS = ("system-health", "lcd-sound-deploy", "ocpp-csms-deploy", "ocpp-reports-deploy", "agent-ops-deploy", "ap-kiosk-deploy", "rfid-deploy", "bastion-deploy")


def validate(task: str, repository: str = "", sha: str = "") -> None:
    if task not in TASKS:
        raise ValueError("Unknown task")
    if task == "system-health":
        if repository or sha:
            raise ValueError("Health task takes no repository or sha")
        return
    expected = {"lcd-sound-deploy": LCD_REPOSITORY,
                "agent-ops-deploy": AGENT_REPOSITORY,
                "ap-kiosk-deploy": KIOSK_REPOSITORY,
                "rfid-deploy": RFID_REPOSITORY,
                "bastion-deploy": BASTION_REPOSITORY,
                "ocpp-reports-deploy": REPORTS_REPOSITORY}.get(task, ALLOWED_REPOSITORY)
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

    if task in ("lcd-sound-deploy", "ocpp-csms-deploy", "ocpp-reports-deploy", "agent-ops-deploy", "ap-kiosk-deploy", "rfid-deploy", "bastion-deploy"):
        from .best_effort import manual_execute
        from .github_state import GitHub
        installer = {
            "lcd-sound-deploy": deploy_lcd_sound,
            "ocpp-csms-deploy": deploy_csms,
            "ocpp-reports-deploy": deploy_reports,
            "agent-ops-deploy": deploy_agent_ops,
            "ap-kiosk-deploy": deploy_ap_kiosk,
            "rfid-deploy": deploy_rfid,
            "bastion-deploy": deploy_bastion,
        }[task]
        name = {"lcd-sound-deploy": "gway-lcd-sound",
                "ocpp-csms-deploy": "ocpp-csms",
                "ocpp-reports-deploy": "ocpp-reports",
                "agent-ops-deploy": "gway-agent-ops",
                "ap-kiosk-deploy": "gway-ap-kiosk",
                "rfid-deploy": "gway-rfid",
                "bastion-deploy": "gway-bastion"}[task]
        print(json.dumps(manual_execute(GitHub(), name, sha, installer), sort_keys=True))
        return

    raise ValueError("Unknown task")


def deploy_csms(sha: str) -> None:
    """Persistently deploy the approved CSMS main commit via its canonical Ansible wrapper.

    The upstream deployer owns incumbent traffic detection and cutover.
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


def deploy_reports(sha: str) -> None:
    """Deploy pinned Reports main through its canonical wrapper."""
    with tempfile.TemporaryDirectory(prefix="reports-deploy-") as directory:
        source = Path(directory) / "source"
        subprocess.run(["git", "clone", "--quiet", "--no-checkout",
                        "https://github.com/arthexis/ocpp-reports.git", str(source)],
                       check=True, timeout=180)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", sha],
                       check=True, timeout=60)
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                         text=True, timeout=20).strip()
        if actual.lower() != sha.lower():
            raise ValueError("Reports checkout SHA mismatch")
        subprocess.run(["bash", "./deploy.sh"], cwd=source, check=True, timeout=900)


def deploy_agent_ops(sha: str) -> None:
    """Deploy pinned Agent Ops through its canonical, owner-managed wrapper.

    Remote does not build virtualenvs or switch the agent executable. The owner
    installer serializes activation, maintains rollback links and verifies the
    installed entrypoint. Remote independently verifies the resulting command.
    """
    with tempfile.TemporaryDirectory(prefix="agent-ops-deploy-") as directory:
        source = Path(directory) / "source"
        subprocess.run(["git", "clone", "--quiet", "--no-checkout",
                        "https://github.com/arthexis/gway-agent-ops.git", str(source)],
                       check=True, timeout=180)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", sha],
                       check=True, timeout=60)
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                         text=True, timeout=20).strip()
        if actual.lower() != sha.lower():
            raise ValueError("Agent Ops checkout SHA mismatch")
        if not (source / "deploy.sh").is_file():
            raise RuntimeError("Agent Ops canonical deploy.sh unavailable")
        subprocess.run(["sh", "./deploy.sh", "--expected-sha", sha.lower()],
                       cwd=source, check=True, timeout=600)
        entry = Path.home() / ".local/bin/agent"
        prefix = Path.home() / ".local/share/gway-agent-ops/releases"
        expected = prefix / sha.lower() / "bin/agent"
        if not entry.is_symlink() or entry.resolve(strict=True) != expected:
            raise RuntimeError("Agent Ops installed command does not match approved SHA")
        for option in ("--help", "--version"):
            subprocess.run([str(entry), option], check=True, timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def deploy_ap_kiosk(sha: str) -> None:
    """Deploy the pinned kiosk main revision via its standalone Ansible wrapper."""
    with tempfile.TemporaryDirectory(prefix="ap-kiosk-deploy-") as directory:
        source = Path(directory) / "source"
        subprocess.run(["git", "clone", "--quiet", "--no-checkout",
                        "https://github.com/arthexis/gway-ap-kiosk.git", str(source)],
                       check=True, timeout=180)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", sha],
                       check=True, timeout=60)
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                         text=True, timeout=20).strip()
        if actual.lower() != sha.lower():
            raise ValueError("AP kiosk checkout SHA mismatch")
        subprocess.run(["bash", "./deploy.sh"], cwd=source, check=True, timeout=600)


def deploy_rfid(sha: str) -> None:
    """Deploy the approved RFID release using its canonical Ansible wrapper."""
    with tempfile.TemporaryDirectory(prefix="rfid-deploy-") as directory:
        source = Path(directory) / "source"
        subprocess.run(["git", "clone", "--quiet", "--no-checkout",
                        "https://github.com/arthexis/gway-rfid.git", str(source)],
                       check=True, timeout=180)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", sha],
                       check=True, timeout=60)
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                         text=True, timeout=20).strip()
        if actual.lower() != sha.lower():
            raise ValueError("RFID checkout SHA mismatch")
        subprocess.run(["sh", "./deploy.sh"], cwd=source, check=True, timeout=900)



def deploy_bastion(sha: str) -> None:
    """Stage Bastion only; never switch active security commands or services."""
    with tempfile.TemporaryDirectory(prefix="bastion-deploy-") as directory:
        source = Path(directory) / "source"
        subprocess.run(["git", "clone", "--quiet", "--no-checkout",
                        "https://github.com/arthexis/gway-bastion.git", str(source)],
                       check=True, timeout=180)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", sha],
                       check=True, timeout=60)
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                         text=True, timeout=20).strip()
        if actual.lower() != sha.lower():
            raise ValueError("Bastion checkout SHA mismatch")
        subprocess.run(["bash", "./deploy.sh"], cwd=source, check=True, timeout=900)
        revision = Path("/opt/gway-bastion/releases") / sha / "REVISION"
        if not revision.is_file() or revision.is_symlink() or revision.read_text().strip() != sha:
            raise RuntimeError("Bastion staged revision cannot be verified")
        print("Bastion release staged only; active runtime unchanged", flush=True)


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
        from gway_remote.public_sound import promote
        checksum = promote(sha)
        print(f"Public sound player: sha256={checksum} release={sha}")
        subprocess.run(["systemctl", "--user", "daemon-reload"],
                       env=user_systemd_env(), check=True, timeout=20)



def main() -> None:
    parser = argparse.ArgumentParser(description="Run an approved gway-001 workload")
    subparsers = parser.add_subparsers(dest="command", required=True)
    execute = subparsers.add_parser("run")
    execute.add_argument("task", choices=TASKS)
    execute.add_argument("--repository", default="")
    execute.add_argument("--sha", default="")
    from .cli.security import register as register_security, dispatch as dispatch_security
    register_security(subparsers, ("bearer","exec"))
    from .cli.deploy import register as register_deploy, dispatch as dispatch_deploy
    register_deploy(subparsers, DEPLOYMENT_TARGETS, ("deploy-targets","reconcile"))
    from .cli.operations import register, dispatch
    register(subparsers, DEPLOYMENT_TARGETS, ("diagnose",))
    watch_parser = subparsers.add_parser("watch", help="One bounded appliance reconciliation tick")
    watch_parser.add_argument("--apply", action="store_true", help="Dispatch eligible deployments and file incidents")
    register(subparsers, DEPLOYMENT_TARGETS, ("status","hardware","network"))
    watchdog_parser = subparsers.add_parser("watchdog", help="Inspect or explicitly configure systemd hardware watchdog")
    watchdog_parser.add_argument("action", choices=("show", "enable", "disable"))
    watchdog_parser.add_argument("--seconds", type=int, default=None)
    watchdog_parser.add_argument("--apply", action="store_true", help="Confirm privileged systemd watchdog configuration")
    watchdog_parser.add_argument("--json", action="store_true")
    subparsers.add_parser("probe-csms", help="Read-only CSMS health diagnosis")
    register(subparsers, DEPLOYMENT_TARGETS, ("logs",))
    report_parser = subparsers.add_parser("report-bundle", help="Export sanitized artifact report")
    report_parser.add_argument("--output", required=True)
    register_deploy(subparsers, DEPLOYMENT_TARGETS, ("retention","deployments","deploy","deploy-batch"))
    register_security(subparsers, ("host-key","wireguard","inspection-host-rotate","inspection-host-pin","register","watchtower"))
    worker_parser = subparsers.add_parser("codex", aliases=["codex-worker"], help="Codex worker and task inspection")
    worker_parser.add_argument("action", choices=("serve", "status", "tasks", "task", "submit", "discover", "veto", "unveto", "approve", "next"))
    worker_parser.add_argument("task_id", nargs="?")
    worker_parser.add_argument("--socket", default=None)
    worker_parser.add_argument("--repo", default=None)
    worker_parser.add_argument("--issue", type=int, default=None)
    worker_parser.add_argument("--kind", default=None)
    worker_parser.add_argument("--priority", default="P2")
    worker_parser.add_argument("--reason", default=None)
    api_parser = subparsers.add_parser("api", help="Run the opt-in loopback HTTP API")
    api_parser.add_argument("--host", default="127.0.0.1")
    api_parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if dispatch_security(args, parser):
        return
    if args.command in ("codex", "codex-worker"):
        if args.action in ("approve", "next"):
            if args.action == "approve" and not args.task_id:
                parser.error("codex approve requires task ID")
            if args.action == "next" and args.task_id:
                parser.error("codex next takes no task ID")
            from .codex_queue import TaskQueue, default_db
            try:
                with TaskQueue(default_db()) as queue:
                    result = queue.approve(args.task_id) if args.action == "approve" else queue.next()
            except ValueError as exc:
                parser.exit(1, f"gway-remote: {exc}\\n")
            print(json.dumps(result, indent=2, sort_keys=True))
            return
        if args.action in ("veto", "unveto"):
            if not args.task_id or (args.action == "veto" and not args.reason):
                parser.error("codex veto requires task ID and --reason; unveto requires task ID")
            from .codex_queue import TaskQueue, default_db
            try:
                with TaskQueue(default_db()) as queue:
                    result = queue.veto(args.task_id, args.reason) if args.action == "veto" else queue.unveto(args.task_id)
            except ValueError as exc:
                parser.exit(1, f"gway-remote: {exc}\\n")
            print(json.dumps(result, indent=2, sort_keys=True))
            return
        if args.action == "discover":
            if args.task_id or args.repo or args.issue is not None or args.kind:
                parser.error("codex discover takes no task metadata")
            from .codex_queue import TaskQueue, default_db
            from .codex_discovery import discover
            try:
                with TaskQueue(default_db()) as queue:
                    result = discover(queue, os.environ.get("GITHUB_TOKEN", ""))
            except (ValueError, OSError) as exc:
                parser.exit(1, f"gway-remote: discovery failed: {exc}\\n")
            print(json.dumps(result, indent=2, sort_keys=True))
            return
        if args.action == "submit":
            if args.task_id or not args.repo or args.issue is None or not args.kind:
                parser.error("codex submit requires --repo, --issue and --kind")
            from .codex_queue import TaskQueue, default_db
            try:
                with TaskQueue(default_db()) as queue:
                    result = queue.admit(args.kind, args.repo, args.issue, args.priority)
            except ValueError as exc:
                parser.exit(1, f"gway-remote: admission rejected: {exc}\\n")
            print(json.dumps(result, indent=2, sort_keys=True))
            return
        if args.action in ("tasks", "task"):
            from .codex_queue import TaskQueue, default_db
            if args.action == "task" and not args.task_id:
                parser.error("codex task requires a task ID")
            if args.action == "tasks" and args.task_id:
                parser.error("codex tasks takes no task ID")
            with TaskQueue(default_db()) as queue:
                result = queue.list() if args.action == "tasks" else queue.get(args.task_id)
            if result is None:
                parser.exit(1, "gway-remote: task not found\\n")
            print(json.dumps(result, indent=2, sort_keys=True))
            return
        if args.task_id:
            parser.error("task ID is only valid for codex task")
        from .codex_worker import main as worker_main
        argv = [args.action]
        if args.socket is not None:
            argv += ["--socket", args.socket]
        return worker_main(argv)
    if args.command == "api":
        from .api import serve
        try:
            serve(args.host, args.port)
        except (ValueError, OSError) as exc:
            parser.exit(1, f"gway-remote: API unavailable: {exc}\\n")
        return
    if dispatch(args, parser):
        return
    if dispatch_deploy(args, parser, deployers={
        "ocpp-csms": deploy_csms, "ocpp-reports": deploy_reports,
        "gway-lcd-sound": deploy_lcd_sound, "gway-agent-ops": deploy_agent_ops,
        "gway-ap-kiosk": deploy_ap_kiosk, "gway-rfid": deploy_rfid,
        "gway-bastion": deploy_bastion,
    }):
        return
    if args.command == "watchdog":
        from .watchdog import inspect, configure, format_watchdog
        if args.action == "show":
            if args.apply or args.seconds is not None:
                parser.error("watchdog show does not accept --apply or --seconds")
            report = inspect()
        else:
            try:
                report = configure(args.action, seconds=args.timeout_seconds, apply=args.apply)
            except (ValueError, PermissionError, OSError, RuntimeError) as exc:
                parser.exit(1, f"gway-remote: watchdog: {exc}\n")
        print(json.dumps(report, indent=2, sort_keys=True) if args.json else
              format_watchdog(report if args.action == "show" else report["watchdog"]))
        return
    if args.command == "probe-csms":
        from .csms_health import csms_probe
        print(json.dumps(csms_probe(), indent=2, sort_keys=True))
        return
    if args.command == "report-bundle":
        from .report_bundle import bundle
        try:
            print(bundle(args.output))
        except (OSError, ValueError) as exc:
            parser.exit(1, f"gway-remote: report unavailable: {exc}\\n")
        return
    if args.command == "watch":
        from .appliance_watch import check
        print(json.dumps(check(apply=args.apply), indent=2, sort_keys=True))
        return
    if args.command == "run":
        from .deployment_policy import require_local_deployment
        require_local_deployment(args.repository)
        try:
            run(args.task, args.repository, args.sha)
        except (ValueError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            parser.exit(1, f"gway-remote: {exc}\n")


if __name__ == "__main__":
    main()
