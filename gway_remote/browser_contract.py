"""Bounded local browser IPC and MCP declarations. No browser/profile access."""
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct

MAX = 32768
TIMEOUT = 7
REF = re.compile(r"[a-f0-9]{32}\Z")
SCENARIOS = ("rfid_history", "heartbeat_expand", "heartbeat_next")
NAMES = ("status", "snapshot", "click", "scenario_run")

def validate_request(req):
    if type(req) is not dict or req.get("operation") not in NAMES:
        raise ValueError("invalid_operation")
    op = req["operation"]
    expected = {"operation"} | ({"ref"} if op == "click" else
                               {"scenario"} if op == "scenario_run" else set())
    if set(req) != expected:
        raise ValueError("invalid_arguments")
    if op == "click" and (type(req["ref"]) is not str or not REF.fullmatch(req["ref"])):
        raise ValueError("invalid_reference")
    if op == "scenario_run" and req["scenario"] not in SCENARIOS:
        raise ValueError("invalid_scenario")
    return req

def declarations():
    tools = []
    for name, description in (
        ("status", "Check whether an operator has opted in an approved Reports tab."),
        ("snapshot", "Return bounded semantic controls and aggregate evidence; no raw page text."),
        ("click", "Activate one fresh reviewed read-only Reports control by opaque reference."),
        ("scenario_run", "Perform one reviewed Reports acceptance step; inspect returned evidence before continuing."),
    ):
        props = {"ref": {"type": "string", "pattern": "^[a-f0-9]{32}$"}} if name == "click" else (
            {"scenario": {"type": "string", "enum": list(SCENARIOS)}} if name == "scenario_run" else {})
        tools.append({"name": name, "description": description,
                      "inputSchema": {"type": "object", "properties": props,
                                      "required": list(props), "additionalProperties": False},
                      "annotations": {"readOnlyHint": name in ("status", "snapshot"),
                                      "destructiveHint": False}})
    return tools

def encode(value):
    data = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
    if not 0 < len(data) <= MAX:
        raise ValueError("message_size")
    return struct.pack("=I", len(data)) + data

def read_exact(read, size):
    result = bytearray()
    while len(result) < size:
        chunk = read(size - len(result))
        if not chunk:
            raise EOFError("peer_closed")
        result.extend(chunk)
    return bytes(result)

def receive(read):
    size = struct.unpack("=I", read_exact(read, 4))[0]
    if not 0 < size <= MAX:
        raise ValueError("message_size")
    value = json.loads(read_exact(read, size))
    if type(value) is not dict:
        raise ValueError("invalid_message")
    return value

def socket_path():
    runtime = Path("/run/user") / str(os.geteuid())
    info = runtime.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise PermissionError("unsafe_runtime")
    directory = runtime / "gway-browser"
    return directory / "bridge.sock"

def check_peer(conn):
    _, uid, _ = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if uid != os.geteuid() or uid == 0:
        raise PermissionError("peer_denied")

def call(req):
    validate_request(req)
    path = socket_path()
    parent = path.parent.lstat()
    info = path.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o077:
        raise PermissionError("unsafe_socket_directory")
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError("unsafe_socket")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(TIMEOUT)
        conn.connect(str(path))
        check_peer(conn)
        conn.sendall(encode(req))
        return validate_result(receive(conn.recv))

def validate_result(value):
    # Strict schema: no arbitrary DOM text, URLs, page content or raw screenshots.
    if type(value) is not dict or set(value) - {"ok", "state", "page", "controls", "evidence"}:
        raise ValueError("invalid_result")
    if type(value.get("ok")) is not bool or value.get("state") not in (
        "ready", "not_enabled", "denied", "stale", "unavailable", "navigation_started",
        "action_started", "ambiguous", "loading"):
        raise ValueError("invalid_result")
    if "page" in value and value["page"] not in ("dashboard", "rfid", "charger", "other"):
        raise ValueError("invalid_page")
    controls = value.get("controls", [])
    if type(controls) is not list or len(controls) > 32:
        raise ValueError("invalid_controls")
    kinds = ("rfid_history", "rfid_next", "charger_detail", "heartbeat_expand", "heartbeat_next")
    for item in controls:
        if (type(item) is not dict or set(item) != {"ref", "kind"} or item["kind"] not in kinds
                or type(item["ref"]) is not str or not REF.fullmatch(item["ref"])):
            raise ValueError("invalid_control")
    evidence = value.get("evidence", {})
    keys = {"rfid_summary_rows", "session_rows", "history_chart", "history_page", "history_pages",
            "heartbeat_groups", "loaded_events", "response_id_header", "soc_header", "operator_admin_hidden"}
    if type(evidence) is not dict or set(evidence) - keys:
        raise ValueError("invalid_evidence")
    for v in evidence.values():
        if type(v) not in (bool, int) or (type(v) is int and not 0 <= v <= 10000000):
            raise ValueError("invalid_evidence_value")
    return value
