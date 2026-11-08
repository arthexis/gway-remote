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
    bearer_parser = subparsers.add_parser("bearer", help="Local Watchtower-only MCP bearer administration")
    bearer_ops = bearer_parser.add_subparsers(dest="bearer_action", required=True)
    bearer_issue = bearer_ops.add_parser("issue", help="Generate a scoped MCP bearer at the local console")
    bearer_issue.add_argument("--days", type=int, default=30)
    bearer_issue.add_argument("--scope", choices=("gway:read", "gway:execute"), default="gway:read")
    bearer_revoke = bearer_ops.add_parser("revoke", help="Revoke an issued bearer by public ID")
    bearer_revoke.add_argument("key_id")
    exec_parser = subparsers.add_parser("exec", help="Root-only Watchtower execution eligibility")
    exec_actions = exec_parser.add_subparsers(dest="exec_action", required=True)
    for action in ("grant", "revoke", "status"):
        exec_action = exec_actions.add_parser(action, help=f"{action} enrollment execution eligibility")
        exec_action.add_argument("node", help="enrolled gway node name")
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
    subparsers.add_parser("host-key", help="Print local SSH ED25519 host public key for independent verification")
    wg_parser = subparsers.add_parser("wireguard", help="WireGuard registration origin and local public identity")
    wg_parser.add_argument("action", choices=("endpoint", "public-key"))
    wg_parser.add_argument("operation", nargs="?", choices=("show", "set"))
    wg_parser.add_argument("value", nargs="?")
    rotate_parser = subparsers.add_parser("inspection-host-rotate", help="Operator-authorized SSH host identity rotation")
    rotate_parser.add_argument("--node", required=True)
    rotate_parser.add_argument("--known-hosts", type=Path, required=True)
    rotate_parser.add_argument("--ssh-config", type=Path, default=Path("/etc/gway-remote/inspection-ssh.conf"))
    rotate_parser.add_argument("--authorize-rotation", action="store_true")
    pin_parser = subparsers.add_parser("inspection-host-pin", help="Explicitly pin attested SSH host identity")
    pin_parser.add_argument("--node", required=True, help="Approved satellite node")
    pin_parser.add_argument("--known-hosts", type=Path, required=True, help="Existing dedicated private known_hosts file")
    pin_parser.add_argument("--ssh-config", type=Path, default=Path("/etc/gway-remote/inspection-ssh.conf"))
    pin_parser.add_argument("--authorize-initial", action="store_true",
                            help="Operator-authorized first pin; never replaces a mismatched host key")
    register_parser = subparsers.add_parser("register", help="Private Watchtower bootstrap URL issuance")
    register_parser.add_argument("target", help="gway-NNN node, status, or revoke")
    register_parser.add_argument("session_id", nargs="?")
    register_parser.add_argument("--minutes", type=int, default=15)
    register_parser.add_argument("--replace", action="store_true", help="issue a server-authorized replacement URL")
    register_parser.add_argument("--repair", dest="repair_host_identity", action="store_true",
                                 help="issue an explicit one-time attestation repair bootstrap")
    register_parser.add_argument("--settings", type=Path, default=Path("/etc/gway-remote/watchtower.json"))
    watchtower_parser = subparsers.add_parser("watchtower", help="Root-only Watchtower enrollment administration")
    watchtower_parser.add_argument("action", choices=("serve", "invite", "register", "revoke", "revoke-bootstrap", "bootstrap-status", "status", "snapshot", "recover", "revoke-host", "rotate-host", "adopt", "attest"))
    watchtower_parser.add_argument("node", nargs="?", help="node ID for adopt or attest")
    watchtower_parser.add_argument("--settings", type=Path, default=Path("/etc/gway-remote/watchtower.json"), help="root-owned Watchtower settings for adopt")
    watchtower_parser.add_argument("--ledger", help="root-owned SQLite enrollment ledger")
    watchtower_parser.add_argument("--public-key", help="independently verified existing WireGuard peer public key")
    watchtower_parser.add_argument("--dry-run", action="store_true", help="inspect without writing ledger")
    watchtower_parser.add_argument("--attest", action="store_true", help="attest SSH host identity atomically during adopt")
    watchtower_parser.add_argument("--host-key-file", type=Path, help="independently verified ED25519 SSH host public key file")
    watchtower_parser.add_argument("--host-key", help="independently verified ED25519 SSH public key (or - for stdin)")
    watchtower_parser.add_argument("--rotate", action="store_true", help="explicit host-key rotation; requires unused invitation token file")
    watchtower_parser.add_argument("--network", help="approved IPv4 allocation CIDR")
    watchtower_parser.add_argument("--gateway", help="approved hub IPv4 address")
    watchtower_parser.add_argument("--config", help="root-owned WireGuard configuration")
    watchtower_parser.add_argument("--backup-dir", help="root-only WireGuard rollback directory")
    watchtower_parser.add_argument("--device")
    watchtower_parser.add_argument("--invitation-id")
    watchtower_parser.add_argument("--session-id")
    watchtower_parser.add_argument("--prior-host-key-file", type=Path)
    watchtower_parser.add_argument("--next-host-key-file", type=Path)
    watchtower_parser.add_argument("--rotation-token-file", type=Path)
    watchtower_parser.add_argument("--authorize-rotation", action="store_true")
    watchtower_parser.add_argument("--minutes", type=int, default=15)
    watchtower_parser.add_argument("--repair", dest="repair_host_identity", action="store_true")
    watchtower_parser.add_argument("--replace", action="store_true")
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
    if args.command == "exec":
        from .watchtower_exec_eligibility import run_action
        try:
            result = run_action(args.exec_action, args.node)
        except (OSError, ValueError, PermissionError, RuntimeError) as exc:
            parser.exit(1, "gway-remote: execution eligibility unavailable: " +
                        type(exc).__name__ + "\\n")
        print(json.dumps(result, sort_keys=True))
        return
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
                if args.session_id or args.repair_host_identity or args.replace:
                    parser.error("register status takes no session ID")
                print(json.dumps(ledger.bootstrap_status(), sort_keys=True))
            elif args.target == "revoke":
                if not args.session_id or args.repair_host_identity or args.replace:
                    parser.error("register revoke requires a session ID")
                print(json.dumps({"revoked": ledger.revoke_bootstrap(args.session_id)}, sort_keys=True))
            else:
                if args.session_id or not DEVICE.fullmatch(args.target):
                    parser.error("register requires exactly one valid node identifier")
                url = ledger.register(args.target, minutes=args.minutes,
                                      public_url=settings["public_url"],
                                      repair_host_identity=args.repair_host_identity, replace=args.replace)["url"]
                print(f"curl -fsSL '{url}' | sudo sh")
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            parser.exit(1, "gway-remote: Watchtower registration unavailable: "
                        + type(exc).__name__ + "\\n")
        return
    if args.command == "bearer":
        # CLI-exclusive operator action. Never registered in MCP, mobile API, or
        # Agent Ops adapters. Issue requires an interactive console to avoid
        # leaking the one-time plaintext token to CI, log capture, or agents.
        if args.bearer_action == "issue" and not (sys.stdin.isatty() and sys.stdout.isatty()):
            parser.exit(1, "gway-remote: issuing a bearer requires an interactive console\\n")
        from .mcp_bearer_cli import assume_auth_identity, BearerAdminError
        try:
            assume_auth_identity()
        except BearerAdminError as exc:
            parser.exit(1, "gway-remote: " + str(exc) + "\n")
        from .mcp_bearer import BearerRegistry
        registry = BearerRegistry("/var/lib/gway-mcp-auth/credentials.sqlite3")
        try:
            if args.bearer_action == "issue":
                if not 1 <= args.days <= 90:
                    parser.error("bearer issue --days must be 1..90")
                print(registry.issue(scope=args.scope, lifetime=args.days * 86400,
                                     operator_approved=(args.scope == "gway:execute")))
                print("Save the credential securely; this value will not be shown again.", file=sys.stderr)
            elif not registry.revoke(args.key_id):
                parser.exit(1, "gway-remote: bearer not found or already revoked\\n")
            else:
                print("Bearer revoked")
        except (OSError, ValueError) as exc:
            parser.exit(1, "gway-remote: local bearer administration unavailable: " + type(exc).__name__ + "\\n")
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
            if args.action in ("adopt", "attest"):
                from .watchtower_settings import adopt_settings
                settings = adopt_settings(args.settings)
                args.ledger = args.ledger or settings["ledger"]
                args.network = args.network or settings["network"]
                args.gateway = args.gateway or settings["gateway"]
                args.config = args.config or settings["config"]
            if not args.ledger or not args.network or not args.gateway:
                parser.error("active Watchtower administration requires --ledger, --network, and --gateway")
            ledger = Ledger(Path(args.ledger), network=args.network, gateway=args.gateway,
                            read_only=args.action in ("adopt", "attest") and args.dry_run)
            if args.action == "adopt":
                if not args.node or not args.public_key or not args.config:
                    parser.error("watchtower adopt requires node, --public-key and --config")
                if not args.attest and args.host_key_file is not None:
                    parser.error("--host-key-file requires --attest for adopt")
                if args.attest and args.host_key_file is None:
                    from .watchtower_attest import host_key_path
                    args.host_key_file = host_key_path(args.node)
                from .watchtower_adopt import adopt
                result = adopt(ledger, node=args.node, public_key=args.public_key,
                               config=Path(args.config), dry_run=args.dry_run,
                               host_key_file=args.host_key_file)
                print(json.dumps(result, sort_keys=True))
                return
            if args.action == "attest":
                if not args.node:
                    parser.error("watchtower attest requires node")
                if args.attest or args.public_key:
                    parser.error("watchtower attest takes neither --attest nor --public-key")
                from .watchtower_attest import attest, host_key_path
                if args.rotate:
                    if args.host_key is None or args.host_key_file is not None:
                        parser.error("--rotate requires --host-key (not --host-key-file)")
                    from .watchtower_attest import rotate_verified_host_key, rotation_token_path
                    if args.rotation_token_file is None:
                        args.rotation_token_file = rotation_token_path(args.node)
                    key = sys.stdin.readline().strip() if args.host_key == "-" else args.host_key
                    print(json.dumps(rotate_verified_host_key(ledger, args.node, key,
                        token_file=args.rotation_token_file, dry_run=args.dry_run), sort_keys=True))
                    return
                if args.host_key is not None and args.host_key_file is not None:
                    parser.error("--host-key and --host-key-file are mutually exclusive")
                if args.host_key is not None:
                    from .watchtower_attest import provision_host_key
                    key = sys.stdin.readline().strip() if args.host_key == "-" else args.host_key
                    args.host_key_file = provision_host_key(args.node, key, dry_run=args.dry_run)
                if args.host_key_file is None:
                    args.host_key_file = host_key_path(args.node)
                if args.dry_run and args.host_key is not None and not args.host_key_file.is_file():
                    from .watchtower_attest import validate_public_key, attest_in_transaction
                    from .watchtower_enrollment import Ledger
                    with ledger._connect() as db:
                        state = attest_in_transaction(db, args.node, validate_public_key(" ".join(key.split()[:2])), dry_run=True)
                    print(json.dumps({"node": args.node, "state": state, "identity_verified": False, "execute_available": False}, sort_keys=True))
                    return
                if not args.host_key_file.is_file():
                    parser.exit(1, f"gway-remote: verified SSH host key missing: {args.host_key_file}\n"
                                f"On {args.node}, run: gway-remote host-key\n"
                                "Verify the output through an independent trusted channel, then provision "
                                "that public key as a protected file on Watchtower and retry with "
                                "--host-key-file PATH (or the default path). Never trust network discovery alone.\n")
                print(json.dumps(attest(ledger, node=args.node,
                                        host_key_file=args.host_key_file,
                                        dry_run=args.dry_run), sort_keys=True))
                return
            if args.action == "snapshot":
                print(json.dumps(ledger.inspection_snapshot(), sort_keys=True))
                return
            if args.action == "invite":
                if not args.device or not DEVICE.fullmatch(args.device):
                    parser.error("watchtower invite requires a valid --device")
                print(json.dumps(ledger.invite(args.device, minutes=args.minutes), sort_keys=True))
                return
            if args.action == "register":
                if not args.device or not args.public_url:
                    parser.error("watchtower register requires --device and --public-url")
                print(json.dumps(ledger.register(args.device, minutes=args.minutes,
                                                 public_url=args.public_url,
                                                 repair_host_identity=args.repair_host_identity, replace=args.replace), sort_keys=True))
                return
            if args.action == "revoke-bootstrap":
                if not args.session_id:
                    parser.error("watchtower revoke-bootstrap requires --session-id")
                print(json.dumps({"revoked": ledger.revoke_bootstrap(args.session_id)}, sort_keys=True))
                return
            if args.action == "revoke-host":
                if not args.device or not DEVICE.fullmatch(args.device):
                    parser.error("watchtower revoke-host requires --device")
                print(json.dumps({"revoked": ledger.revoke_host_identity(args.device)}))
                return
            if args.action == "rotate-host":
                if not args.device or not DEVICE.fullmatch(args.device):
                    parser.error("watchtower rotate-host requires --device")
                files = (args.prior_host_key_file, args.next_host_key_file, args.rotation_token_file)
                if any(value is None for value in files):
                    parser.error("rotate-host requires both host key files and rotation token file")
                from .inspection_ssh_trust import trusted_file
                for value in files:
                    trusted_file(value, secret=True)
                prior, following, token = (value.read_text().strip() for value in files)
                transition = ledger.rotate_host_identity(
                    args.device, previous_key=prior, next_key=following,
                    invitation_token=token, authorized=args.authorize_rotation,
                )
                print(json.dumps({"rotated": True, "transition": transition}, sort_keys=True))
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
    if args.command == "inspection-host-rotate":
        from .deployment_policy import INVENTORY
        from .host_trust import rotate_from_watchtower
        try:
            proc = subprocess.run(
                ["ansible-inventory", "-i", str(INVENTORY), "--host", args.node],
                check=True, capture_output=True, text=True, timeout=15,
            )
            hostvars = json.loads(proc.stdout)
            approved = {args.node} if hostvars.get("remote_inspection_allowed") is True else set()
            if not approved:
                raise ValueError("inspection target not approved")
            changed = rotate_from_watchtower(
                args.node, approved, args.known_hosts,
                authorize_rotation=args.authorize_rotation, ssh_config=args.ssh_config,
            )
        except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            parser.exit(1, "gway-remote: host rotation denied: " + type(exc).__name__ + "\n")
        print(json.dumps({"node": args.node, "rotated": changed}, sort_keys=True))
        return
    if args.command == "inspection-host-pin":
        from .deployment_policy import INVENTORY
        from .host_trust import pin_from_watchtower
        try:
            import subprocess
            proc = subprocess.run(
                ["ansible-inventory", "-i", str(INVENTORY), "--host", args.node],
                check=True, capture_output=True, text=True, timeout=15,
            )
            hostvars = json.loads(proc.stdout)
            approved = {args.node} if hostvars.get("remote_inspection_allowed") is True else set()
            if not approved:
                raise ValueError("inspection target not approved")
            changed = pin_from_watchtower(
                args.node, approved, args.known_hosts,
                authorize_initial=args.authorize_initial, ssh_config=args.ssh_config,
            )
        except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            parser.exit(1, "gway-remote: host pin denied: " + type(exc).__name__ + "\\n")
        print(json.dumps({"node": args.node, "pin_created": changed}, sort_keys=True))
        return
    if args.command == "host-key":
        from .wireguard_satellite import _ssh_host_public_key
        try:
            print(_ssh_host_public_key())
        except (OSError, ValueError) as exc:
            parser.exit(1, f"gway-remote: SSH host public key unavailable: {exc}\n")
        return
    if args.command == "wireguard":
        if args.action == "public-key":
            if args.operation or args.value:
                parser.error("wireguard public-key takes no arguments")
            from .wireguard_identity import public_key
            try:
                print(public_key())
            except (ValueError, OSError, RuntimeError) as exc:
                parser.exit(1, f"gway-remote: local WireGuard public key unavailable: {exc}\\n")
            return
        if not args.operation:
            parser.error("wireguard endpoint requires show or set")
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
