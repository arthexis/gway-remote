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
    if "logs" in names:
        logs_parser = subparsers.add_parser("logs", help="Inspect local installation logs")
        logs_parser.add_argument("component", nargs="?", choices=tuple(name for name, _ in targets))
        logs_parser.add_argument("--lines", type=int, default=None)

def dispatch(args, parser):
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
