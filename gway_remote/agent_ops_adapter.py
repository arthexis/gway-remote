"""Narrow adapter to the installed Agent Ops CLI, without shell or queue access."""
import json
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
