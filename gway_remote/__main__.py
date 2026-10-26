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
SIM_REPOSITORY = "arthexis/ocpp-simulator"
AGENT_REPOSITORY = "arthexis/gway-agent-ops"
KIOSK_REPOSITORY = "arthexis/gway-ap-kiosk"
RFID_REPOSITORY = "arthexis/gway-rfid"
BASTION_REPOSITORY = "arthexis/gway-bastion"
TASKS = ("system-health", "ocpp-simulator", "lcd-sound-deploy", "ocpp-csms-deploy", "ocpp-reports-deploy", "ocpp-simulator-deploy", "agent-ops-deploy", "ap-kiosk-deploy", "rfid-deploy", "bastion-deploy")


def validate(task: str, repository: str = "", sha: str = "") -> None:
    if task not in TASKS:
        raise ValueError("Unknown task")
    if task == "system-health":
        if repository or sha:
            raise ValueError("Health task takes no repository or sha")
        return
    expected = {"lcd-sound-deploy": LCD_REPOSITORY,
                "ocpp-simulator-deploy": SIM_REPOSITORY,
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

    if task in ("lcd-sound-deploy", "ocpp-csms-deploy", "ocpp-reports-deploy", "ocpp-simulator-deploy", "agent-ops-deploy", "ap-kiosk-deploy", "rfid-deploy", "bastion-deploy"):
        from .best_effort import manual_execute
        from .github_state import GitHub
        installer = {
            "lcd-sound-deploy": deploy_lcd_sound,
            "ocpp-csms-deploy": deploy_csms,
            "ocpp-reports-deploy": deploy_reports,
            "ocpp-simulator-deploy": deploy_simulator,
            "agent-ops-deploy": deploy_agent_ops,
            "ap-kiosk-deploy": deploy_ap_kiosk,
            "rfid-deploy": deploy_rfid,
            "bastion-deploy": deploy_bastion,
        }[task]
        name = {"lcd-sound-deploy": "gway-lcd-sound",
                "ocpp-csms-deploy": "ocpp-csms",
                "ocpp-reports-deploy": "ocpp-reports",
                "ocpp-simulator-deploy": "ocpp-simulator",
                "agent-ops-deploy": "gway-agent-ops",
                "ap-kiosk-deploy": "gway-ap-kiosk",
                "rfid-deploy": "gway-rfid",
                "bastion-deploy": "gway-bastion"}[task]
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
    """Install a pinned Agent Ops CLI without running Codex or adopting credentials."""
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
        # Keep installed releases independent of the operator's CODEX_HOME.
        prefix = Path.home() / ".local/share/gway-agent-ops"
        releases = prefix / "releases"
        destination = releases / sha.lower()
        bin_dir = Path.home() / ".local/bin"
        entry = bin_dir / "agent"
        if not destination.exists():
            releases.mkdir(parents=True, exist_ok=True)
            # Build in the final location: pip console scripts embed the venv
            # interpreter's absolute path, so renaming a venv is unsafe.
            try:
                subprocess.run([sys.executable, "-m", "venv", str(destination)],
                               check=True, timeout=90)
                subprocess.run([str(destination / "bin/pip"), "install", "--no-deps", str(source)],
                               check=True, timeout=300)
                subprocess.run([str(destination / "bin/agent"), "--help"], check=True, timeout=30)
            except Exception:
                import shutil
                shutil.rmtree(destination, ignore_errors=True)
                raise
        else:
            subprocess.run([str(destination / "bin/agent"), "--help"], check=True, timeout=30)
        bin_dir.mkdir(parents=True, exist_ok=True)
        # Atomic update: the existing CLI remains in place until the replacement is ready.
        import uuid
        temporary = bin_dir / (".agent-" + uuid.uuid4().hex)
        try:
            temporary.symlink_to(destination / "bin/agent")
            os.replace(temporary, entry)
        finally:
            temporary.unlink(missing_ok=True)
        # Deliberately do not run agent adopt, Codex, or issue execution here.


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
    export_parser = subparsers.add_parser("deploy-targets", help="Export authoritative deployment targets")
    export_parser.add_argument("--json", action="store_true")
    inspection = subparsers.add_parser("reconcile", help="Read-only appliance deployment report")
    inspection.add_argument("--dry-run", action="store_true", help="Do not deploy (always read-only)")
    diagnose_parser = subparsers.add_parser("diagnose", help="Read-only appliance deployment troubleshooting")
    diagnose_parser.add_argument("component", nargs="?", choices=tuple(name for name, _ in DEPLOYMENT_TARGETS))
    diagnose_parser.add_argument("--json", action="store_true")
    diagnose_parser.add_argument("--lines", type=int, default=30)
    watch_parser = subparsers.add_parser("watch", help="One bounded appliance reconciliation tick")
    watch_parser.add_argument("--apply", action="store_true", help="Dispatch eligible deployments and file incidents")
    status_parser = subparsers.add_parser("status", help="Inspect local attempts and health")
    status_parser.add_argument("--json", action="store_true")
    subparsers.add_parser("probe-csms", help="Read-only CSMS health diagnosis")
    logs_parser = subparsers.add_parser("logs", help="Inspect local installation logs")
    logs_parser.add_argument("component", nargs="?", choices=tuple(name for name, _ in DEPLOYMENT_TARGETS))
    logs_parser.add_argument("--lines", type=int, default=None)
    report_parser = subparsers.add_parser("report-bundle", help="Export sanitized artifact report")
    report_parser.add_argument("--output", required=True)
    deployments_parser = subparsers.add_parser("deployments", help="Inspect configured appliance deployments")
    deployments_parser.add_argument("repository", nargs="?", choices=[name for name, _ in DEPLOYMENT_TARGETS])
    deployments_parser.add_argument("--json", action="store_true")
    deployments_parser.add_argument("--node", default=None, help="Inventory node (read-only; no remote connection)")
    deploy_parser = subparsers.add_parser("deploy", help="Trigger GitHub Appliance Deploy workflow")
    from .deploy_dispatch import TARGETS
    deploy_parser.add_argument("repository", nargs="?", help="Repository name or hyphen-word selector (matches all approved targets)")
    deploy_parser.add_argument("--all", action="store_true", help="Deploy all repositories")
    deploy_parser.add_argument("--node", default="gway-001", help="Deployment node (currently gway-001 only)")
    deploy_parser.add_argument("--follow", action="store_true", help="Watch the dispatched workflow until completion")
    batch_parser = subparsers.add_parser("deploy-batch", help="Deploy appliance revisions")
    batch_parser.add_argument("--target", choices=tuple(name for name, _ in DEPLOYMENT_TARGETS), default=None)
    batch_parser.add_argument("--all", action="store_true", help="Explicitly reinstall all latest main revisions regardless of prior attempts or CI")
    batch_parser.add_argument("--now", action="store_true", help="Bypass quiet period for operator-requested batch")
    batch_parser.add_argument("--retry-failed", action="store_true", help="Explicitly retry failed revisions, never installed or interrupted ones")
    wg_parser = subparsers.add_parser("wireguard", help="Configure WireGuard registration origin")
    wg_parser.add_argument("action", choices=("endpoint",))
    wg_parser.add_argument("operation", choices=("show", "set"))
    wg_parser.add_argument("value", nargs="?")
    register_parser = subparsers.add_parser("register", help="Private Watchtower bootstrap URL issuance")
    register_parser.add_argument("target", help="gway-NNN node, status, or revoke")
    register_parser.add_argument("session_id", nargs="?")
    register_parser.add_argument("--minutes", type=int, default=15)
    register_parser.add_argument("--settings", type=Path, default=Path("/etc/gway-remote/watchtower.json"))
    watchtower_parser = subparsers.add_parser("watchtower", help="Root-only Watchtower enrollment administration")
    watchtower_parser.add_argument("action", choices=("serve", "invite", "register", "revoke", "revoke-bootstrap", "bootstrap-status", "status", "recover"))
    watchtower_parser.add_argument("--ledger", help="root-owned SQLite enrollment ledger")
    watchtower_parser.add_argument("--network", help="approved IPv4 allocation CIDR")
    watchtower_parser.add_argument("--gateway", help="approved hub IPv4 address")
    watchtower_parser.add_argument("--config", help="root-owned WireGuard configuration")
    watchtower_parser.add_argument("--backup-dir", help="root-only WireGuard rollback directory")
    watchtower_parser.add_argument("--device")
    watchtower_parser.add_argument("--invitation-id")
    watchtower_parser.add_argument("--session-id")
    watchtower_parser.add_argument("--minutes", type=int, default=15)
    watchtower_parser.add_argument("--host", default="127.0.0.1")
    watchtower_parser.add_argument("--port", type=int, default=8788)
    watchtower_parser.add_argument("--public-url", help="approved public HTTPS enrollment URL")
    watchtower_parser.add_argument("--wireguard-endpoint", help="approved public UDP host:port")
    watchtower_parser.add_argument("--read-only-stage", action="store_true", help="serve health and reject enrollment without opening ledger/config/WireGuard")
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
    if args.command == "register":
        from .watchtower_enrollment import Ledger
        from .wireguard_enrollment_contract import DEVICE
        try:
            if os.geteuid() != 0:
                raise PermissionError("Watchtower registration requires root")
            path = args.settings
            if path.is_symlink() or not path.is_file():
                raise ValueError("Watchtower operator settings missing or unsafe")
            stat = path.stat()
            if stat.st_uid != 0 or stat.st_mode & 0o077:
                raise PermissionError("Watchtower operator settings must be root-owned 0600")
            settings = json.loads(path.read_text())
            ledger = Ledger(Path(settings["ledger"]), network=settings["network"],
                            gateway=settings["gateway"])
            if args.target == "status":
                if args.session_id:
                    parser.error("register status takes no session ID")
                print(json.dumps(ledger.bootstrap_status(), sort_keys=True))
            elif args.target == "revoke":
                if not args.session_id:
                    parser.error("register revoke requires a session ID")
                print(json.dumps({"revoked": ledger.revoke_bootstrap(args.session_id)}, sort_keys=True))
            else:
                if args.session_id or not DEVICE.fullmatch(args.target):
                    parser.error("register requires exactly one valid gway-NNN node")
                url = ledger.register(args.target, minutes=args.minutes,
                                      public_url=settings["public_url"])["url"]
                print(f"curl -fsSL '{url}' | sudo sh")
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            parser.exit(1, "gway-remote: Watchtower registration unavailable: "
                        + type(exc).__name__ + "\\n")
        return
    if args.command == "watchtower":
        from .watchtower_enrollment import Ledger, Provisioner, SubprocessWireGuard, serve
        from .wireguard_enrollment_contract import DEVICE
        try:
            if args.read_only_stage:
                if args.action == "status":
                    print(json.dumps({"mode": "read_only_stage", "wireguard_mutation": False}, sort_keys=True))
                    return
                if args.action != "serve" or not args.public_url or not args.wireguard_endpoint:
                    parser.error("read-only stage only supports serve/status with public endpoint configuration")
                serve(None, host=args.host, port=args.port, public_url=args.public_url,
                      wireguard_endpoint=args.wireguard_endpoint, read_only_stage=True)
                return
            if os.geteuid() != 0:
                parser.exit(1, "gway-remote: Watchtower administration requires root or sudo\n")
            if not args.ledger or not args.network or not args.gateway:
                parser.error("active Watchtower administration requires --ledger, --network, and --gateway")
            ledger = Ledger(Path(args.ledger), network=args.network, gateway=args.gateway)
            if args.action == "invite":
                if not args.device or not DEVICE.fullmatch(args.device):
                    parser.error("watchtower invite requires a valid --device")
                print(json.dumps(ledger.invite(args.device, minutes=args.minutes), sort_keys=True))
                return
            if args.action == "register":
                if not args.device or not args.public_url:
                    parser.error("watchtower register requires --device and --public-url")
                print(json.dumps(ledger.register(args.device, minutes=args.minutes,
                                                 public_url=args.public_url), sort_keys=True))
                return
            if args.action == "revoke-bootstrap":
                if not args.session_id:
                    parser.error("watchtower revoke-bootstrap requires --session-id")
                print(json.dumps({"revoked": ledger.revoke_bootstrap(args.session_id)}, sort_keys=True))
                return
            if args.action == "bootstrap-status":
                print(json.dumps(ledger.bootstrap_status(), sort_keys=True))
                return
            if args.action == "revoke":
                if not args.invitation_id:
                    parser.error("watchtower revoke requires --invitation-id")
                print(json.dumps({"revoked": ledger.revoke(args.invitation_id)}, sort_keys=True))
                return
            if args.action == "status":
                print(json.dumps(ledger.status(), sort_keys=True))
                return
            if not args.config or not args.backup_dir:
                parser.error(f"watchtower {args.action} requires --config and --backup-dir")
            provisioner = Provisioner(ledger, Path(args.config), Path(args.backup_dir), SubprocessWireGuard())
            if args.action == "recover":
                print(json.dumps({"recovered": provisioner.recover()}, sort_keys=True))
                return
            if not args.public_url or not args.wireguard_endpoint:
                parser.error("watchtower serve requires --public-url and --wireguard-endpoint")
            serve(provisioner, host=args.host, port=args.port, public_url=args.public_url,
                  wireguard_endpoint=args.wireguard_endpoint)
        except (OSError, ValueError, RuntimeError) as exc:
            parser.exit(1, f"gway-remote: Watchtower operation unavailable: {exc}\n")
        return
    if args.command == "wireguard":
        from .wireguard_endpoint import endpoint, set_endpoint
        if args.operation == "set" and not args.value:
            parser.error("wireguard endpoint set requires an HTTPS origin")
        if args.operation == "show" and args.value:
            parser.error("wireguard endpoint show takes no value")
        try:
            result = set_endpoint(args.value) if args.operation == "set" else endpoint()
        except (ValueError, OSError) as exc:
            parser.exit(1, f"gway-remote: WireGuard endpoint unavailable: {exc}\\n")
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "deploy-targets":
        from .target_export import export_targets
        data = export_targets()
        print(json.dumps(data, sort_keys=True) if args.json else
              "\\n".join(row["repository"] for row in data["targets"]))
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
    if args.command == "diagnose":
        from .diagnostics import diagnose, format_diagnosis
        try:
            report = diagnose(args.component, lines=args.lines)
            print(json.dumps(report, indent=2, sort_keys=True) if args.json else format_diagnosis(report))
        except (OSError, ValueError) as exc:
            parser.exit(1, f"gway-remote: diagnosis unavailable: {exc}\\n")
        return
    if args.command == "watch":
        from .appliance_watch import check
        print(json.dumps(check(apply=args.apply), indent=2, sort_keys=True))
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
    if args.command == "deployments":
        from .deployments import inventory, format_inventory
        try:
            result = inventory(args.repository, node=args.node)
            print(json.dumps(result, indent=2, sort_keys=True) if args.json else format_inventory(result))
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            parser.exit(1, f"gway-remote: deployments unavailable: {exc}\\n")
        return
    if args.command == "deploy":
        if args.all == bool(args.repository):
            parser.error("deploy requires either a repository or --all (not both)")
        from .deploy_dispatch import dispatch, follow_run, resolve_targets
        try:
            targets = ("all",) if args.all else resolve_targets(args.repository)
            failures = []
            for target in targets:
                try:
                    message = dispatch(target, node=args.node)
                    print(message, flush=True)
                    if args.follow:
                        follow_run(message)
                except (ValueError, RuntimeError) as exc:
                    failures.append(f"{target}: {exc}")
                    print(f"gway-remote: {target}: {exc}", file=sys.stderr, flush=True)
            if failures:
                parser.exit(1, f"gway-remote: {len(failures)} deployment request(s) failed\n")
        except ValueError as exc:
            parser.exit(1, f"gway-remote: {exc}\n")
        return
    if args.command == "deploy-batch":
        from .deployment_policy import require_local_deployment
        require_local_deployment(args.target if args.all and args.target else None)
        if args.target and not args.all:
            parser.error("--target requires --all")
        if args.all and (args.now or args.retry_failed):
            parser.error("--all cannot be combined with legacy eligibility flags")
        if args.retry_failed and not args.now:
            parser.error("--retry-failed requires --now")
        from datetime import datetime, timezone
        from .best_effort import execute
        from .github_state import GitHub
        try:
            from .status import installed_revision
            def verify_release(name, sha):
                if name == "gway-lcd-sound":
                    installed = installed_revision(name)
                    if installed != sha[:12]:
                        raise RuntimeError(
                            f"LCD Sound installed revision mismatch: expected {sha[:12]}, observed {installed or 'unknown'}"
                        )
            result = execute(GitHub(), datetime.now(timezone.utc), {
                "ocpp-csms": deploy_csms,
                "ocpp-reports": deploy_reports,
                "ocpp-simulator": deploy_simulator,
                "gway-lcd-sound": deploy_lcd_sound,
                "gway-agent-ops": deploy_agent_ops,
                "gway-ap-kiosk": deploy_ap_kiosk,
                "gway-rfid": deploy_rfid,
                "gway-bastion": deploy_bastion,
            }, bypass_quiet=args.now, retry_failed=args.retry_failed, verify=verify_release, deploy_all=args.all, target=args.target)
            print(json.dumps(result, indent=2, sort_keys=True))
            if result["decision"] == "failed":
                parser.exit(1, "gway-remote: installation failed: {} at {}\\n".format(result["failed_component"], result["failed_sha"]))
            if args.all and result["decision"] != "completed":
                parser.exit(1, "gway-remote: manual deployment incomplete: {} ({})\\n".format(result["decision"], result.get("reason", "unknown")))
            if result["decision"] == "blocked":
                parser.exit(1, "gway-remote: batch blocked\\n")
            if args.now and result["decision"] in ("waiting", "blocked", "stale", "idle"):
                parser.exit(1, "gway-remote: manual batch not deployed ({}: {})\\n".format(result["decision"], result.get("reason", "unknown")))
            if any(item["status"] == "failed" for item in result["results"]):
                parser.exit(1, "gway-remote: one or more installations failed\\n")
        except (ValueError, RuntimeError, OSError) as exc:
            parser.exit(1, f"gway-remote: {exc}\\n")
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
