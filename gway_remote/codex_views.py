"""Read-only Codex task views shared by CLI and mobile API."""
from __future__ import annotations
import json
from uuid import UUID
from .codex_queue import TaskQueue, default_db

def _validate_id(value):
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("invalid_task_id") from exc

def _view(task, execution):
    if execution is None:
        return {"task": task, "execution": None}
    record = dict(execution)
    try:
        record["artifacts"] = json.loads(record.pop("artifacts_json", "[]"))
    except (ValueError, TypeError):
        record["artifacts"] = []
    return {"task": task, "execution": record}

def list_tasks(limit=50, *, db=None):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid_limit")
    with TaskQueue(db or default_db()) as queue:
        return {"tasks": [_view(task, queue.execution(task["id"])) for task in queue.list(limit)]}

def task_detail(task_id, *, db=None):
    task_id = _validate_id(task_id)
    with TaskQueue(db or default_db()) as queue:
        task = queue.get(task_id)
        if task is None:
            raise ValueError("task_not_found")
        return _view(task, queue.execution(task_id))

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Inspect Codex task results (read-only)")
    sub = parser.add_subparsers(dest="action", required=True)
    tasks = sub.add_parser("tasks")
    tasks.add_argument("--limit", type=int, default=50)
    for name in ("task", "result"):
        sub.add_parser(name).add_argument("task_id")
    args = parser.parse_args(argv)
    try:
        data = list_tasks(args.limit) if args.action == "tasks" else task_detail(args.task_id)
        if args.action == "result":
            data = data["execution"]
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
