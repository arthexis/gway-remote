"""CLI deployment argument registration and dispatch."""
import json
import sys

def register(subparsers, targets, names):
    if "deploy-targets" in names:
        export_parser = subparsers.add_parser("deploy-targets", help="Export authoritative deployment targets")
        export_parser.add_argument("--json", action="store_true")
    if "reconcile" in names:
        inspection = subparsers.add_parser("reconcile", help="Read-only appliance deployment report")
        inspection.add_argument("--dry-run", action="store_true", help="Do not deploy (always read-only)")
    if "retention" in names:
        retention_parser = subparsers.add_parser("retention", help="Read-only managed release retention preview")
        retention_parser.add_argument("repository", nargs="?", choices=[name for name, _ in targets])
        retention_parser.add_argument("--dry-run", action="store_true", help="Explicit preview (always read-only)")
        retention_parser.add_argument("--json", action="store_true")
    if "deployments" in names:
        deployments_parser = subparsers.add_parser("deployments", help="Inspect configured appliance deployments")
        deployments_parser.add_argument("repository", nargs="?", choices=[name for name, _ in targets])
        deployments_parser.add_argument("--json", action="store_true")
        deployments_parser.add_argument("--inspect", action="store_true", help="Explicit read-only Bastion SSH probe")
        deployments_parser.add_argument("--node", default=None, help="Inventory node (read-only; no remote connection)")
    if "deploy" in names:
        deploy_parser = subparsers.add_parser("deploy", help="Trigger GitHub Appliance Deploy workflow")
        deploy_parser.add_argument("repository", nargs="?", help="Repository name or hyphen-word selector (matches all approved targets)")
        deploy_parser.add_argument("--all", action="store_true", help="Deploy all repositories")
        deploy_parser.add_argument("--node", default="gway-001", help="Deployment node (currently gway-001 only)")
        deploy_parser.add_argument("--follow", action="store_true", help="Watch the dispatched workflow until completion")
    if "deploy-batch" in names:
        batch_parser = subparsers.add_parser("deploy-batch", help="Deploy appliance revisions")
        batch_parser.add_argument("--target", choices=tuple(name for name, _ in targets), default=None)
        batch_parser.add_argument("--all", action="store_true", help="Explicitly reinstall all latest main revisions regardless of prior attempts or CI")
        batch_parser.add_argument("--now", action="store_true", help="Bypass quiet period for operator-requested batch")
        batch_parser.add_argument("--retry-failed", action="store_true", help="Explicitly retry failed revisions, never installed or interrupted ones")

def dispatch(args, parser, *, deployers):
    if args.command == "deploy-targets":
        from ..target_export import export_targets
        data = export_targets()
        print(json.dumps(data, sort_keys=True) if args.json else
              "\\n".join(row["repository"] for row in data["targets"]))
        return True
    if args.command == "reconcile":
        from ..github_state import GitHub, report
        from ..attempts import attempted_shas
        try:
            print(json.dumps(report(GitHub(), attempts=attempted_shas()), indent=2, sort_keys=True))
        except Exception as exc:
            parser.exit(1, f"gway-remote: reconciliation unavailable: {exc}\n")
        return True
    if args.command == "retention":
        from ..retention_preview import preview, format_preview
        try:
            result = preview(args.repository)
            print(json.dumps(result, indent=2, sort_keys=True) if args.json else format_preview(result))
        except (OSError, ValueError, RuntimeError) as exc:
            parser.exit(1, f"gway-remote: retention preview unavailable: {exc}\n")
        return True
    if args.command == "deployments":
        from ..deployments import inventory, format_inventory
        try:
            result = inventory(args.repository, node=args.node)
            if args.inspect:
                import subprocess
                from ..deployment_policy import INVENTORY
                from ..remote_inspection import inspect
                if not args.node:
                    raise ValueError("--inspect requires explicit --node")
                proc = subprocess.run(
                    ["ansible-inventory", "-i", str(INVENTORY), "--host", args.node],
                    check=True, capture_output=True, text=True, timeout=15,
                )
                hostvars = json.loads(proc.stdout)
                approved = {args.node} if hostvars.get("remote_inspection_allowed") is True else set()
                result["remote_inspection"] = inspect(args.node, approved=approved)
            output = json.dumps(result, indent=2, sort_keys=True) if args.json else format_inventory(result)
            if args.inspect and not args.json:
                output += "\\nRemote inspection: " + json.dumps(result["remote_inspection"], sort_keys=True)
            print(output)
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            parser.exit(1, f"gway-remote: deployments unavailable: {exc}\\n")
        return True
    if args.command == "deploy":
        if args.all == bool(args.repository):
            parser.error("deploy requires either a repository or --all (not both)")
        from ..deploy_dispatch import dispatch, follow_run, resolve_targets
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
        return True
    if args.command == "deploy-batch":
        from ..deployment_policy import require_local_deployment
        require_local_deployment(args.target if args.all and args.target else None)
        if args.target and not args.all:
            parser.error("--target requires --all")
        if args.all and (args.now or args.retry_failed):
            parser.error("--all cannot be combined with legacy eligibility flags")
        if args.retry_failed and not args.now:
            parser.error("--retry-failed requires --now")
        from datetime import datetime, timezone
        from ..best_effort import execute
        from ..github_state import GitHub
        try:
            from ..status import installed_revision
            def verify_release(name, sha):
                if name == "gway-lcd-sound":
                    installed = installed_revision(name)
                    if installed != sha[:12]:
                        raise RuntimeError(
                            f"LCD Sound installed revision mismatch: expected {sha[:12]}, observed {installed or 'unknown'}"
                        )
            result = execute(GitHub(), datetime.now(timezone.utc), deployers, bypass_quiet=args.now, retry_failed=args.retry_failed, verify=verify_release, deploy_all=args.all, target=args.target)
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
        return True
    return False
