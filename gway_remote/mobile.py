"""Explicit mobile operations; no arbitrary shell execution."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import tempfile
import subprocess
import shutil

from .benchmark import echo
from . import agent_ops_adapter
from .codex_views import list_tasks, task_detail
from .codex_issue_views import list_assignments
from .csms_health import csms_probe
from .simulator_network import discover
from . import simulator_runner
from .status import status

LCD_DIR = Path.home() / ".local" / "state" / "lcd-lockfiles"
LCD_EVENT = "lcd-event-mobile.lck"
SOUNDS = ("ok", "notice", "attention", "warning", "error", "busy", "critical")

CSMS_VIEWS = {
    "status": ("status",),
    "chargers": ("chargers",),
    "charge-points": ("cps",),
    "transactions": ("txn",),
    "events": ("events",),
    "alerts": ("alerts",),
    "rfid-report": ("rfid", "report"),
    "report": ("report",),
}


def csms_view(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"view"}:
        raise ValueError("invalid_arguments")
    view = arguments["view"]
    if not isinstance(view, str) or view not in CSMS_VIEWS:
        raise ValueError("invalid_csms_view")
    executable = shutil.which("ocpp-csms") or str(Path.home() / ".local/bin/ocpp-csms")
    if not Path(executable).is_file():
        raise RuntimeError("csms_cli_not_found")
    try:
        completed = subprocess.run(
            [executable, "--data-dir", str(Path.home() / "ocpp-csms-data"), *CSMS_VIEWS[view]],
            capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("csms_command_failed")
    if completed.returncode:
        raise RuntimeError("csms_command_failed")
    return {"view": view, "output": completed.stdout[:65536], "truncated": len(completed.stdout) > 65536}

OPERATIONS = {"probe-csms": csms_probe, "status": status,
              "status-quick": lambda: status(depth="quick")}


def commands():
    return ([{"name": "agent-preview", "read_only": True, "arguments": {
                "ref": {"type": "string", "required": True}}}]
            + [{"name": name, "arguments": {}, "read_only": True} for name in OPERATIONS]
            + [{"name": "agent-observe", "read_only": True, "arguments": {
                "ref": {"type": "string", "required": True},
                "at": {"type": "string", "required": True}}}]
            + [{"name": "agent-issue", "read_only": False, "arguments": {
                "ref": {"type": "string", "required": True},
                "at": {"type": "string", "required": True}}}]
            + [{"name": "agent-issues", "read_only": True, "arguments": {}},
                {"name": "agent-status", "read_only": True, "arguments": {}}]
            + [{"name": "codex-issues", "read_only": True, "arguments": {}},
                {"name": "codex-tasks", "read_only": True, "arguments": {}},
                {"name": "codex-task", "read_only": True, "arguments": {
                    "task_id": {"type": "string", "required": True}}}]
            + [{"name": "benchmark-echo", "read_only": True, "arguments": {
                "payload": {"type": "string", "max_length": 4096, "required": True}}}]
            + [{"name": name, "read_only": name in ("simulator-status", "simulator-results"), "arguments": {}}
               for name in ("simulator-start", "simulator-stop", "simulator-status", "simulator-results")]
            + [{"name": "csms-view", "read_only": True, "arguments": {
                "view": {"type": "choice", "choices": list(CSMS_VIEWS), "required": True}}}]
            + [{"name": "simulator-discover", "read_only": True, "arguments": {
                "host": {"type": "string", "required": False},
                "port": {"type": "integer", "required": False}}},
               {"name": "sound-motifs", "read_only": True, "arguments": {}},
               {"name": "sound-play", "read_only": False, "arguments": {
                "sound": {"type": "choice", "choices": list(SOUNDS), "required": True},
                "motif": {"type": "string", "required": False}}},
               {"name": "lcd-message", "read_only": False, "arguments": {
                "line1": {"type": "string", "max_length": 16, "required": True},
                "line2": {"type": "string", "max_length": 16, "required": True},
                "duration_seconds": {"type": "integer", "min": 30, "max": 300, "required": False}}}])


def lcd_message(arguments):
    if not isinstance(arguments, dict) or not {"line1", "line2"} <= set(arguments) or set(arguments) - {"line1", "line2", "duration_seconds"}:
        raise ValueError("invalid_arguments")
    duration = arguments.get("duration_seconds", 30)
    if type(duration) is not int or not 30 <= duration <= 300 or duration % 30:
        raise ValueError("invalid_lcd_duration")
    lines = [arguments["line1"], arguments["line2"]]
    if any(not isinstance(line, str) or len(line) > 16 or
           any(ord(char) < 32 or ord(char) > 126 for char in line) for line in lines):
        raise ValueError("lcd_lines_must_be_16_printable_ascii_characters_or_less")
    if not any(lines):
        raise ValueError("lcd_message_empty")
    # The existing gway-lcd-sound runner consumes event lockfiles and
    # resumes its normal rotation when this timestamp expires.
    LCD_DIR.mkdir(parents=True, exist_ok=True)
    expires = (datetime.now(timezone.utc) + timedelta(seconds=duration)).isoformat()
    fd, name = tempfile.mkstemp(prefix=".lcd-mobile-", dir=LCD_DIR)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(f"{lines[0]}\n{lines[1]}\n{expires}\n")
        os.replace(name, LCD_DIR / LCD_EVENT)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return {"queued": True, "duration_seconds": duration}


def sound_motifs(arguments):
    if arguments:
        raise ValueError("invalid_arguments")
    try:
        completed = subprocess.run(["/usr/local/bin/sound", "--list-motifs"],
                                   check=True, timeout=8, capture_output=True, text=True)
        motifs = json.loads(completed.stdout)
        if not isinstance(motifs, list) or any(not isinstance(m, str) for m in motifs):
            raise ValueError("invalid motif list")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        raise RuntimeError("sound_motifs_failed")
    return {"motifs": motifs}


def sound_play(arguments):
    if (not isinstance(arguments, dict) or set(arguments) - {"sound", "motif"} or
            arguments.get("sound") not in SOUNDS):
        raise ValueError("invalid_sound")
    motif = arguments.get("motif")
    if motif is not None and (not isinstance(motif, str) or
                              not motif or len(motif) > 100 or
                              any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in motif)):
        raise ValueError("invalid_motif")
    cmd = ["/usr/local/bin/sound"]
    if motif:
        cmd.extend(["--motif", motif])
    cmd.append(arguments["sound"])
    try:
        subprocess.run(cmd, check=True, timeout=8,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError("sound_play_failed")
    return {"played": arguments["sound"], "motif": motif}


def codex_mobile(name, arguments):
    if not isinstance(arguments, dict):
        raise ValueError("invalid_arguments")
    if name == "codex-tasks":
        if arguments:
            raise ValueError("invalid_arguments")
        return list_tasks()
    if set(arguments) != {"task_id"} or not isinstance(arguments["task_id"], str):
        raise ValueError("invalid_arguments")
    return task_detail(arguments["task_id"])


def execute(name, arguments):
    if name == "agent-preview":
        return agent_ops_adapter.preview_issue(arguments)
    if name == "agent-observe":
        return agent_ops_adapter.observe_issue(arguments)
    if name == "agent-issue":
        return agent_ops_adapter.send_issue(arguments)
    if name == "agent-issues":
        return agent_ops_adapter.issues(arguments)
    if name == "agent-status":
        return agent_ops_adapter.status(arguments)
    if name == "codex-issues":
        if not isinstance(arguments, dict) or arguments:
            raise ValueError("invalid_arguments")
        return list_assignments()
    if name in ("codex-tasks", "codex-task"):
        return codex_mobile(name, arguments)
    if name == "benchmark-echo":
        return echo(arguments)
    if name == "csms-view":
        return csms_view(arguments)
    if name in ("simulator-start", "simulator-stop", "simulator-status", "simulator-results"):
        return {"simulator-start": simulator_runner.start, "simulator-stop": simulator_runner.stop,
                "simulator-status": simulator_runner.status, "simulator-results": simulator_runner.results}[name](arguments)
    if name == "simulator-discover":
        if not isinstance(arguments, dict) or set(arguments) - {"host", "port"}:
            raise ValueError("invalid_arguments")
        return discover(**arguments)
    if name == "sound-motifs":
        return sound_motifs(arguments)
    if name == "sound-play":
        return sound_play(arguments)
    if name == "lcd-message":
        return lcd_message(arguments)
    if not isinstance(name, str) or name not in OPERATIONS:
        raise ValueError("unknown_command")
    if not isinstance(arguments, dict) or arguments:
        raise ValueError("invalid_arguments")
    return OPERATIONS[name]()
