"""Explicit mobile operations; no arbitrary shell execution."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import tempfile
import subprocess

from .csms_health import csms_probe
from .simulator_network import discover
from .status import status

LCD_DIR = Path.home() / ".local" / "state" / "lcd-lockfiles"
LCD_EVENT = "lcd-event-mobile.lck"
SOUNDS = ("ok", "notice", "attention", "warning", "error", "busy", "critical")

OPERATIONS = {"probe-csms": csms_probe, "status": status}


def commands():
    return ([{"name": name, "arguments": {}, "read_only": True} for name in OPERATIONS]
            + [{"name": "simulator-discover", "read_only": True, "arguments": {
                "host": {"type": "string", "required": False},
                "port": {"type": "integer", "required": False}}},
               {"name": "sound-play", "read_only": False, "arguments": {
                "sound": {"type": "choice", "choices": list(SOUNDS), "required": True}}},
               {"name": "lcd-message", "read_only": False, "arguments": {
                "line1": {"type": "string", "max_length": 16, "required": True},
                "line2": {"type": "string", "max_length": 16, "required": True}}}])


def lcd_message(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"line1", "line2"}:
        raise ValueError("invalid_arguments")
    lines = [arguments["line1"], arguments["line2"]]
    if any(not isinstance(line, str) or len(line) > 16 or
           any(ord(char) < 32 or ord(char) > 126 for char in line) for line in lines):
        raise ValueError("lcd_lines_must_be_16_printable_ascii_characters_or_less")
    if not any(lines):
        raise ValueError("lcd_message_empty")
    # The existing gway-lcd-sound runner consumes event lockfiles and
    # resumes its normal rotation when this timestamp expires.
    LCD_DIR.mkdir(parents=True, exist_ok=True)
    expires = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    fd, name = tempfile.mkstemp(prefix=".lcd-mobile-", dir=LCD_DIR)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(f"{lines[0]}\n{lines[1]}\n{expires}\n")
        os.replace(name, LCD_DIR / LCD_EVENT)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return {"queued": True, "duration_seconds": 30}


def sound_play(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"sound"} or arguments["sound"] not in SOUNDS:
        raise ValueError("invalid_sound")
    try:
        subprocess.run(["/usr/local/bin/sound", arguments["sound"]], check=True,
                       timeout=8, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError("sound_play_failed")
    return {"played": arguments["sound"]}


def execute(name, arguments):
    if name == "simulator-discover":
        if not isinstance(arguments, dict) or set(arguments) - {"host", "port"}:
            raise ValueError("invalid_arguments")
        return discover(**arguments)
    if name == "sound-play":
        return sound_play(arguments)
    if name == "lcd-message":
        return lcd_message(arguments)
    if not isinstance(name, str) or name not in OPERATIONS:
        raise ValueError("unknown_command")
    if not isinstance(arguments, dict) or arguments:
        raise ValueError("invalid_arguments")
    return OPERATIONS[name]()
