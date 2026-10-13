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


class AgentOpsError(RuntimeError):
    """Non-sensitive, stable CLI failure code for the authenticated API."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _run(arguments):
    command = arguments[0]
    # A synchronous issue invocation can run longer than the read APIs.
    # Do not automatically retry timeouts: the dispatch may have been accepted.
    timeout = 20 if command in ("issues", "status", "observe", "submit") else 1800
    try:
        completed = subprocess.run(
            [_agent_path(), *arguments, "--json"],
            capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AgentOpsError("agent_result_unconfirmed" if command in ("issue", "submit")
                            else "agent_cli_timeout") from exc
    except OSError as exc:
        raise AgentOpsError("agent_cli_failed") from exc
    if len(completed.stdout) > MAX_OUTPUT:
        raise AgentOpsError("agent_response_too_large")
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise AgentOpsError("agent_invalid_json") from exc
    if (not isinstance(payload, dict) or payload.get("schema_version") != 1
            or payload.get("command") != command
            or not isinstance(payload.get("status"), str)
            or "data" not in payload or "error" not in payload):
        raise AgentOpsError("agent_invalid_contract")
    status = payload["status"]
    if completed.returncode != 0 or status not in ("ok", "finished"):
        codes = {"busy": "agent_busy", "duplicate": "agent_duplicate"}
        raise AgentOpsError(codes.get(status, "agent_execution_failed"))
    if command == "issue" and status != "finished":
        raise AgentOpsError("agent_result_unconfirmed")
    if command != "issue" and status != "ok":
        raise AgentOpsError("agent_invalid_contract")
    if not isinstance(payload["data"], dict):
        raise AgentOpsError("agent_invalid_contract")
    return payload


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
    return _run(["submit", ref, "--at", at])

def observe_issue(arguments):
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
    return _run(["observe", ref, "--at", at])
