"""Watchtower enrollment, identity and security CLI contracts."""
import json
import os
import subprocess
import sys
from pathlib import Path

def register(subparsers, names):
    if "bearer" in names:
        bearer_parser = subparsers.add_parser("bearer", help="Local Watchtower-only MCP bearer administration")
        bearer_ops = bearer_parser.add_subparsers(dest="bearer_action", required=True)
        bearer_issue = bearer_ops.add_parser("issue", help="Generate a scoped MCP bearer at the local console")
        bearer_issue.add_argument("--days", type=int, default=30)
        bearer_issue.add_argument("--scope", choices=("gway:read", "gway:execute"), default="gway:read")
        bearer_revoke = bearer_ops.add_parser("revoke", help="Revoke an issued bearer by public ID")
        bearer_revoke.add_argument("key_id")
    if "exec" in names:
        exec_parser = subparsers.add_parser("exec", help="Root-only Watchtower execution eligibility")
        exec_actions = exec_parser.add_subparsers(dest="exec_action", required=True)
        for action in ("grant", "revoke", "status"):
            exec_action = exec_actions.add_parser(action, help=f"{action} enrollment execution eligibility")
            exec_action.add_argument("node", help="enrolled gway node name")
    if "host-key" in names:
        subparsers.add_parser("host-key", help="Print local SSH ED25519 host public key for independent verification")
    if "wireguard" in names:
        wg_parser = subparsers.add_parser("wireguard", help="WireGuard registration origin and local public identity")
        wg_parser.add_argument("action", choices=("endpoint", "public-key"))
        wg_parser.add_argument("operation", nargs="?", choices=("show", "set"))
        wg_parser.add_argument("value", nargs="?")
    if "inspection-host-rotate" in names:
        rotate_parser = subparsers.add_parser("inspection-host-rotate", help="Operator-authorized SSH host identity rotation")
        rotate_parser.add_argument("--node", required=True)
        rotate_parser.add_argument("--known-hosts", type=Path, required=True)
        rotate_parser.add_argument("--ssh-config", type=Path, default=Path("/etc/gway-remote/inspection-ssh.conf"))
        rotate_parser.add_argument("--authorize-rotation", action="store_true")
    if "inspection-host-pin" in names:
        pin_parser = subparsers.add_parser("inspection-host-pin", help="Explicitly pin attested SSH host identity")
        pin_parser.add_argument("--node", required=True, help="Approved satellite node")
        pin_parser.add_argument("--known-hosts", type=Path, required=True, help="Existing dedicated private known_hosts file")
        pin_parser.add_argument("--ssh-config", type=Path, default=Path("/etc/gway-remote/inspection-ssh.conf"))
        pin_parser.add_argument("--authorize-initial", action="store_true",
                                help="Operator-authorized first pin; never replaces a mismatched host key")
    if "register" in names:
        register_parser = subparsers.add_parser("register", help="Private Watchtower bootstrap URL issuance")
        register_parser.add_argument("target", help="gway-NNN node, status, or revoke")
        register_parser.add_argument("session_id", nargs="?")
        register_parser.add_argument("--minutes", type=int, default=15)
        register_parser.add_argument("--replace", action="store_true", help="issue a server-authorized replacement URL")
        register_parser.add_argument("--repair", dest="repair_host_identity", action="store_true",
                                     help="issue an explicit one-time attestation repair bootstrap")
        register_parser.add_argument("--settings", type=Path, default=Path("/etc/gway-remote/watchtower.json"))
    if "watchtower" in names:
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

def dispatch(args, parser):
    if args.command == "exec":
        from ..watchtower_exec_eligibility import run_action
        try:
            result = run_action(args.exec_action, args.node)
        except (OSError, ValueError, PermissionError, RuntimeError) as exc:
            parser.exit(1, "gway-remote: execution eligibility unavailable: " +
                        type(exc).__name__ + "\\n")
        print(json.dumps(result, sort_keys=True))
        return True
    if args.command == "register":
        from ..watchtower_enrollment import Ledger
        from ..wireguard_enrollment_contract import DEVICE
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
        return True
    if args.command == "bearer":
        # CLI-exclusive operator action. Never registered in MCP, mobile API, or
        # Agent Ops adapters. Issue requires an interactive console to avoid
        # leaking the one-time plaintext token to CI, log capture, or agents.
        if args.bearer_action == "issue" and not (sys.stdin.isatty() and sys.stdout.isatty()):
            parser.exit(1, "gway-remote: issuing a bearer requires an interactive console\\n")
        from ..mcp_bearer_cli import assume_auth_identity, BearerAdminError
        try:
            assume_auth_identity()
        except BearerAdminError as exc:
            parser.exit(1, "gway-remote: " + str(exc) + "\n")
        from ..mcp_bearer import BearerRegistry
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
        return True
    if args.command == "watchtower":
        from ..watchtower_enrollment import Ledger, Provisioner, SubprocessWireGuard, serve
        from ..wireguard_enrollment_contract import DEVICE
        try:
            if args.read_only_stage:
                if args.action == "status":
                    print(json.dumps({"mode": "read_only_stage", "wireguard_mutation": False}, sort_keys=True))
                    return True
                if args.action != "serve" or not args.public_url or not args.wireguard_endpoint:
                    parser.error("read-only stage only supports serve/status with public endpoint configuration")
                serve(None, host=args.host, port=args.port, public_url=args.public_url,
                      wireguard_endpoint=args.wireguard_endpoint, read_only_stage=True)
                return True
            if os.geteuid() != 0:
                parser.exit(1, "gway-remote: Watchtower administration requires root or sudo\n")
            if args.action in ("adopt", "attest"):
                from ..watchtower_settings import adopt_settings
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
                    from ..watchtower_attest import host_key_path
                    args.host_key_file = host_key_path(args.node)
                from ..watchtower_adopt import adopt
                result = adopt(ledger, node=args.node, public_key=args.public_key,
                               config=Path(args.config), dry_run=args.dry_run,
                               host_key_file=args.host_key_file)
                print(json.dumps(result, sort_keys=True))
                return True
            if args.action == "attest":
                if not args.node:
                    parser.error("watchtower attest requires node")
                if args.attest or args.public_key:
                    parser.error("watchtower attest takes neither --attest nor --public-key")
                from ..watchtower_attest import attest, host_key_path
                if args.rotate:
                    if args.host_key is None or args.host_key_file is not None:
                        parser.error("--rotate requires --host-key (not --host-key-file)")
                    from ..watchtower_attest import rotate_verified_host_key, rotation_token_path
                    if args.rotation_token_file is None:
                        args.rotation_token_file = rotation_token_path(args.node)
                    key = sys.stdin.readline().strip() if args.host_key == "-" else args.host_key
                    print(json.dumps(rotate_verified_host_key(ledger, args.node, key,
                        token_file=args.rotation_token_file, dry_run=args.dry_run), sort_keys=True))
                    return True
                if args.host_key is not None and args.host_key_file is not None:
                    parser.error("--host-key and --host-key-file are mutually exclusive")
                if args.host_key is not None:
                    from ..watchtower_attest import provision_host_key
                    key = sys.stdin.readline().strip() if args.host_key == "-" else args.host_key
                    args.host_key_file = provision_host_key(args.node, key, dry_run=args.dry_run)
                if args.host_key_file is None:
                    args.host_key_file = host_key_path(args.node)
                if args.dry_run and args.host_key is not None and not args.host_key_file.is_file():
                    from ..watchtower_attest import validate_public_key, attest_in_transaction
                    from ..watchtower_enrollment import Ledger
                    with ledger._connect() as db:
                        state = attest_in_transaction(db, args.node, validate_public_key(" ".join(key.split()[:2])), dry_run=True)
                    print(json.dumps({"node": args.node, "state": state, "identity_verified": False, "execute_available": False}, sort_keys=True))
                    return True
                if not args.host_key_file.is_file():
                    parser.exit(1, f"gway-remote: verified SSH host key missing: {args.host_key_file}\n"
                                f"On {args.node}, run: gway-remote host-key\n"
                                "Verify the output through an independent trusted channel, then provision "
                                "that public key as a protected file on Watchtower and retry with "
                                "--host-key-file PATH (or the default path). Never trust network discovery alone.\n")
                print(json.dumps(attest(ledger, node=args.node,
                                        host_key_file=args.host_key_file,
                                        dry_run=args.dry_run), sort_keys=True))
                return True
            if args.action == "snapshot":
                print(json.dumps(ledger.inspection_snapshot(), sort_keys=True))
                return True
            if args.action == "invite":
                if not args.device or not DEVICE.fullmatch(args.device):
                    parser.error("watchtower invite requires a valid --device")
                print(json.dumps(ledger.invite(args.device, minutes=args.minutes), sort_keys=True))
                return True
            if args.action == "register":
                if not args.device or not args.public_url:
                    parser.error("watchtower register requires --device and --public-url")
                print(json.dumps(ledger.register(args.device, minutes=args.minutes,
                                                 public_url=args.public_url,
                                                 repair_host_identity=args.repair_host_identity, replace=args.replace), sort_keys=True))
                return True
            if args.action == "revoke-bootstrap":
                if not args.session_id:
                    parser.error("watchtower revoke-bootstrap requires --session-id")
                print(json.dumps({"revoked": ledger.revoke_bootstrap(args.session_id)}, sort_keys=True))
                return True
            if args.action == "revoke-host":
                if not args.device or not DEVICE.fullmatch(args.device):
                    parser.error("watchtower revoke-host requires --device")
                print(json.dumps({"revoked": ledger.revoke_host_identity(args.device)}))
                return True
            if args.action == "rotate-host":
                if not args.device or not DEVICE.fullmatch(args.device):
                    parser.error("watchtower rotate-host requires --device")
                files = (args.prior_host_key_file, args.next_host_key_file, args.rotation_token_file)
                if any(value is None for value in files):
                    parser.error("rotate-host requires both host key files and rotation token file")
                from ..inspection_ssh_trust import trusted_file
                for value in files:
                    trusted_file(value, secret=True)
                prior, following, token = (value.read_text().strip() for value in files)
                transition = ledger.rotate_host_identity(
                    args.device, previous_key=prior, next_key=following,
                    invitation_token=token, authorized=args.authorize_rotation,
                )
                print(json.dumps({"rotated": True, "transition": transition}, sort_keys=True))
                return True
            if args.action == "bootstrap-status":
                print(json.dumps(ledger.bootstrap_status(), sort_keys=True))
                return True
            if args.action == "revoke":
                if not args.invitation_id:
                    parser.error("watchtower revoke requires --invitation-id")
                print(json.dumps({"revoked": ledger.revoke(args.invitation_id)}, sort_keys=True))
                return True
            if args.action == "status":
                print(json.dumps(ledger.status(), sort_keys=True))
                return True
            if not args.config or not args.backup_dir:
                parser.error(f"watchtower {args.action} requires --config and --backup-dir")
            provisioner = Provisioner(ledger, Path(args.config), Path(args.backup_dir), SubprocessWireGuard())
            if args.action == "recover":
                print(json.dumps({"recovered": provisioner.recover()}, sort_keys=True))
                return True
            if not args.public_url or not args.wireguard_endpoint:
                parser.error("watchtower serve requires --public-url and --wireguard-endpoint")
            serve(provisioner, host=args.host, port=args.port, public_url=args.public_url,
                  wireguard_endpoint=args.wireguard_endpoint)
        except (OSError, ValueError, RuntimeError) as exc:
            parser.exit(1, f"gway-remote: Watchtower operation unavailable: {exc}\n")
        return True
    if args.command == "inspection-host-rotate":
        from ..deployment_policy import INVENTORY
        from ..host_trust import rotate_from_watchtower
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
        return True
    if args.command == "inspection-host-pin":
        from ..deployment_policy import INVENTORY
        from ..host_trust import pin_from_watchtower
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
        return True
    if args.command == "host-key":
        from ..wireguard_satellite import _ssh_host_public_key
        try:
            print(_ssh_host_public_key())
        except (OSError, ValueError) as exc:
            parser.exit(1, f"gway-remote: SSH host public key unavailable: {exc}\n")
        return True
    if args.command == "wireguard":
        if args.action == "public-key":
            if args.operation or args.value:
                parser.error("wireguard public-key takes no arguments")
            from ..wireguard_identity import public_key
            try:
                print(public_key())
            except (ValueError, OSError, RuntimeError) as exc:
                parser.exit(1, f"gway-remote: local WireGuard public key unavailable: {exc}\\n")
            return True
        if not args.operation:
            parser.error("wireguard endpoint requires show or set")
        from ..wireguard_endpoint import endpoint, set_endpoint
        if args.operation == "set" and not args.value:
            parser.error("wireguard endpoint set requires an HTTPS origin")
        if args.operation == "show" and args.value:
            parser.error("wireguard endpoint show takes no value")
        try:
            result = set_endpoint(args.value) if args.operation == "set" else endpoint()
        except (ValueError, OSError) as exc:
            parser.exit(1, f"gway-remote: WireGuard endpoint unavailable: {exc}\\n")
        print(json.dumps(result, sort_keys=True))
        return True
    return False
