"""Local service, worker, watchdog and constrained workload CLI."""
import json
import os
import subprocess

def register(subparsers, names, tasks):
    if "run" in names:
        execute = subparsers.add_parser("run")
        execute.add_argument("task", choices=tasks)
        execute.add_argument("--repository", default="")
        execute.add_argument("--sha", default="")
    if "watch" in names:
        watch_parser = subparsers.add_parser("watch", help="One bounded appliance reconciliation tick")
        watch_parser.add_argument("--apply", action="store_true", help="Dispatch eligible deployments and file incidents")
    if "watchdog" in names:
        watchdog_parser = subparsers.add_parser("watchdog", help="Inspect or explicitly configure systemd hardware watchdog")
        watchdog_parser.add_argument("action", choices=("show", "enable", "disable"))
        watchdog_parser.add_argument("--seconds", type=int, default=None)
        watchdog_parser.add_argument("--apply", action="store_true", help="Confirm privileged systemd watchdog configuration")
        watchdog_parser.add_argument("--json", action="store_true")
    if "probe-csms" in names:
        subparsers.add_parser("probe-csms", help="Read-only CSMS health diagnosis")
    if "report-bundle" in names:
        report_parser = subparsers.add_parser("report-bundle", help="Export sanitized artifact report")
        report_parser.add_argument("--output", required=True)
    if "codex" in names:
        worker_parser = subparsers.add_parser("codex", aliases=["codex-worker"], help="Codex worker and task inspection")
        worker_parser.add_argument("action", choices=("serve", "status", "tasks", "task", "submit", "discover", "veto", "unveto", "approve", "next"))
        worker_parser.add_argument("task_id", nargs="?")
        worker_parser.add_argument("--socket", default=None)
        worker_parser.add_argument("--repo", default=None)
        worker_parser.add_argument("--issue", type=int, default=None)
        worker_parser.add_argument("--kind", default=None)
        worker_parser.add_argument("--priority", default="P2")
        worker_parser.add_argument("--reason", default=None)
    if "api" in names:
        api_parser = subparsers.add_parser("api", help="Run the opt-in loopback HTTP API")
        api_parser.add_argument("--host", default="127.0.0.1")
        api_parser.add_argument("--port", type=int, default=8765)

def dispatch(args, parser, *, run_task):
    if args.command == "run":
        from ..deployment_policy import require_local_deployment
        require_local_deployment(args.repository)
        try:
            run_task(args.task, args.repository, args.sha)
        except (ValueError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            parser.exit(1, f"gway-remote: {exc}\n")
        return True

    if args.command == "watch":
        from ..appliance_watch import check
        print(json.dumps(check(apply=args.apply), indent=2, sort_keys=True))
        return True
    if args.command == "watchdog":
        from ..watchdog import inspect, configure, format_watchdog
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
        return True
    if args.command == "probe-csms":
        from ..csms_health import csms_probe
        print(json.dumps(csms_probe(), indent=2, sort_keys=True))
        return True
    if args.command == "report-bundle":
        from ..report_bundle import bundle
        try:
            print(bundle(args.output))
        except (OSError, ValueError) as exc:
            parser.exit(1, f"gway-remote: report unavailable: {exc}\\n")
        return True
    if args.command in ("codex", "codex-worker"):
        if args.action in ("approve", "next"):
            if args.action == "approve" and not args.task_id:
                parser.error("codex approve requires task ID")
            if args.action == "next" and args.task_id:
                parser.error("codex next takes no task ID")
            from ..codex_queue import TaskQueue, default_db
            try:
                with TaskQueue(default_db()) as queue:
                    result = queue.approve(args.task_id) if args.action == "approve" else queue.next()
            except ValueError as exc:
                parser.exit(1, f"gway-remote: {exc}\\n")
            print(json.dumps(result, indent=2, sort_keys=True))
            return True
        if args.action in ("veto", "unveto"):
            if not args.task_id or (args.action == "veto" and not args.reason):
                parser.error("codex veto requires task ID and --reason; unveto requires task ID")
            from ..codex_queue import TaskQueue, default_db
            try:
                with TaskQueue(default_db()) as queue:
                    result = queue.veto(args.task_id, args.reason) if args.action == "veto" else queue.unveto(args.task_id)
            except ValueError as exc:
                parser.exit(1, f"gway-remote: {exc}\\n")
            print(json.dumps(result, indent=2, sort_keys=True))
            return True
        if args.action == "discover":
            if args.task_id or args.repo or args.issue is not None or args.kind:
                parser.error("codex discover takes no task metadata")
            from ..codex_queue import TaskQueue, default_db
            from ..codex_discovery import discover
            try:
                with TaskQueue(default_db()) as queue:
                    result = discover(queue, os.environ.get("GITHUB_TOKEN", ""))
            except (ValueError, OSError) as exc:
                parser.exit(1, f"gway-remote: discovery failed: {exc}\\n")
            print(json.dumps(result, indent=2, sort_keys=True))
            return True
        if args.action == "submit":
            if args.task_id or not args.repo or args.issue is None or not args.kind:
                parser.error("codex submit requires --repo, --issue and --kind")
            from ..codex_queue import TaskQueue, default_db
            try:
                with TaskQueue(default_db()) as queue:
                    result = queue.admit(args.kind, args.repo, args.issue, args.priority)
            except ValueError as exc:
                parser.exit(1, f"gway-remote: admission rejected: {exc}\\n")
            print(json.dumps(result, indent=2, sort_keys=True))
            return True
        if args.action in ("tasks", "task"):
            from ..codex_queue import TaskQueue, default_db
            if args.action == "task" and not args.task_id:
                parser.error("codex task requires a task ID")
            if args.action == "tasks" and args.task_id:
                parser.error("codex tasks takes no task ID")
            with TaskQueue(default_db()) as queue:
                result = queue.list() if args.action == "tasks" else queue.get(args.task_id)
            if result is None:
                parser.exit(1, "gway-remote: task not found\\n")
            print(json.dumps(result, indent=2, sort_keys=True))
            return True
        if args.task_id:
            parser.error("task ID is only valid for codex task")
        from ..codex_worker import main as worker_main
        argv = [args.action]
        if args.socket is not None:
            argv += ["--socket", args.socket]
        worker_main(argv)
        return True
    if args.command == "api":
        from ..api import serve
        try:
            serve(args.host, args.port)
        except (ValueError, OSError) as exc:
            parser.exit(1, f"gway-remote: API unavailable: {exc}\\n")
        return True
    return False
