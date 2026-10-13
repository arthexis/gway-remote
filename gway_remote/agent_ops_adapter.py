"""Narrow adapter to the installed Agent Ops CLI, without shell or queue access."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

MAX_OUTPUT = 1024 * 1024


def _agent_path():
    executable = shutil.which("agent") or str(Path.home() / ".local/bin/agent")
    if not Path(executable).is_file():
        raise RuntimeError("agent_cli_not_found")
    return executable


def _run(arguments):
    try:
        completed = subprocess.run(
            [_agent_path(), *arguments, "--json"],
            capture_output=True, text=True, timeout=20, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("agent_cli_timeout") from exc
    except OSError as exc:
        raise RuntimeError("agent_cli_failed") from exc
    if completed.returncode != 0:
        raise RuntimeError("agent_cli_failed")
    if len(completed.stdout) > MAX_OUTPUT:
        raise RuntimeError("agent_response_too_large")
    try:
        return json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("agent_invalid_json") from exc


def issues(arguments):
    if type(arguments) is not dict or arguments:
        raise ValueError("invalid_arguments")
    return _run(["issues"])


def status(arguments):
    if type(arguments) is not dict or arguments:
        raise ValueError("invalid_arguments")
    return _run(["status"])

# The Agent Ops CLI is responsible for trust gating and deduplicating an
# identical issue/timestamp submission. Remote must never mint a replacement
# timestamp on a retry.
ISSUE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}#[1-9][0-9]*$")


def send_issue(arguments):
    if type(arguments) is not dict or set(arguments) != {"ref", "at"}:
        raise ValueError("invalid_arguments")
    ref, at = arguments["ref"], arguments["at"]
    if type(ref) is not str or not ISSUE_REF.fullmatch(ref):
        raise ValueError("invalid_issue_ref")
    if type(at) is not str or len(at) != 20 or not at.endswith("Z"):
        raise ValueError("invalid_timestamp")
    try:
        parsed = datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("invalid_timestamp") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != at:
        raise ValueError("invalid_timestamp")
    return _run(["issue", ref, "--at", at])
