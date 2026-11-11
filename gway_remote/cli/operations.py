"""Read-only CLI commands and argparse contracts."""
import json

def register(subparsers, targets, names):
    if "diagnose" in names:
        diagnose_parser = subparsers.add_parser("diagnose", help="Read-only appliance deployment troubleshooting")
        diagnose_parser.add_argument("component", nargs="?", choices=tuple(name for name, _ in targets))
        diagnose_parser.add_argument("--json", action="store_true")
        diagnose_parser.add_argument("--lines", type=int, default=30)
    if "status" in names:
        status_parser = subparsers.add_parser("status", help="Inspect local attempts and health")
        status_parser.add_argument("--json", action="store_true")
    if "hardware" in names:
        hardware_parser = subparsers.add_parser("hardware", help="Read-only optional local RTC and ambient thermometer")
        hardware_parser.add_argument("--json", action="store_true")
    if "network" in names:
        network_parser = subparsers.add_parser("network", help="Read-only eth0/wlan0/wlan1 network snapshot")
        network_parser.add_argument("--json", action="store_true")
    if "mcp" in names:
        mcp = subparsers.add_parser("mcp", help="Read-only node-owned MCP diagnostics")
        sections = mcp.add_subparsers(dest="mcp_section", required=True)
        provider = sections.add_parser("provider", help="Inspect an installed provider")
        actions = provider.add_subparsers(dest="mcp_action", required=True)
        check = actions.add_parser("check", help="Check the trusted manifest and live catalog")
        check.add_argument("source_id")
        check.add_argument("--watchtower-catalog", metavar="JSON_FILE",
                           help="Optional sanitized mcp_catalog_inspect JSON snapshot; never fetches OAuth")
        check.add_argument("--json", action="store_true")
    if "node" in names:
        node_parser = subparsers.add_parser("node", help="Read-only Watchtower node onboarding diagnosis")
        node_ops = node_parser.add_subparsers(dest="node_action", required=True)
        doctor = node_ops.add_parser("doctor", help="Inspect local enrollment and pin evidence, without SSH")
        doctor.add_argument("node", help="enrolled gway node name")
        doctor.add_argument("--json", action="store_true")
    if "logs" in names:
        logs_parser = subparsers.add_parser("logs", help="Inspect local installation logs")
        logs_parser.add_argument("component", nargs="?", choices=tuple(name for name, _ in targets))
        logs_parser.add_argument("--lines", type=int, default=None)

def dispatch(args, parser):
    if args.command == "node":
        from ..node_onboarding_doctor import diagnose_node, format_diagnosis
        try:
            report = diagnose_node(args.node)
        except (OSError, ValueError, TypeError):
            parser.exit(2, "gway-remote: invalid node diagnosis input\n")
        print(json.dumps(report, indent=2, sort_keys=True)
              if args.json else format_diagnosis(report))
        # A report's construction alone is never proof of operational health.
        # Exit 0 only when the node is ready for a *separate* authorized test.
        if not report["ready_for_operator_test"]:
            parser.exit(1)
        return True
    if args.command == "mcp":
        if args.mcp_section != "provider" or args.mcp_action != "check":
            parser.exit(2, "gway-remote: unsupported MCP diagnosis\n")
        from ..mcp_provider_diagnostics import (
            check_provider, format_provider_check, load_watchtower_catalog,
        )
        try:
            snapshot = (load_watchtower_catalog(args.watchtower_catalog)
                        if args.watchtower_catalog is not None else None)
            report = check_provider(args.source_id, watchtower_catalog=snapshot)
        except (OSError, ValueError, TypeError):
            # No paths, exception text, tokens, provider arguments or stderr.
            parser.exit(2, "gway-remote: invalid MCP diagnostic input\n")
        print(json.dumps(report, indent=2, sort_keys=True) if args.json
              else format_provider_check(report))
        if report["state"] != "available" or report["watchtower"]["state"] == "differs_snapshot":
            parser.exit(1)
        return True
    if args.command == "network":
        from ..network_diagnostics import inspect, format_network
        result = inspect()
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else format_network(result))
        return True
    if args.command == "hardware":
        from ..hardware_diagnostics import inspect, format_hardware
        result = inspect()
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else format_hardware(result))
        return True
    if args.command == "logs":
        from ..logs import list_logs, read_log
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
        return True
    if args.command == "diagnose":
        from ..diagnostics import diagnose, format_diagnosis
        try:
            report = diagnose(args.component, lines=args.lines)
            print(json.dumps(report, indent=2, sort_keys=True) if args.json else format_diagnosis(report))
        except (OSError, ValueError) as exc:
            parser.exit(1, f"gway-remote: diagnosis unavailable: {exc}\\n")
        return True
    if args.command == "status":
        from ..status import status, format_status
        result = status()
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else format_status(result))
        return True
    return False
