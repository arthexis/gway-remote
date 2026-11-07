"""Bounded MCP stdio client for registered, pinned providers."""
import json
import os
import selectors
import subprocess
import time

from .mcp_source_registry import SourceRegistration
from .mcp_tool_scope import required_scope


class SourceProtocolError(RuntimeError):
    pass


_MAX_MESSAGE = 262144
_PROTOCOL = "2025-03-26"


class _Session:
    def __init__(self, registration, timeout):
        if not isinstance(registration, SourceRegistration) or not registration.enabled:
            raise SourceProtocolError("source not enabled")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 30:
            raise ValueError("invalid timeout")
        self.registration = registration
        self.deadline = time.monotonic() + timeout
        self.buffer = bytearray()
        self.process = None

    def __enter__(self):
        # Caller must provision the trusted executable and restricted OS identity.
        # No shell, inherited credentials, network endpoint, or caller-supplied argv.
        if os.geteuid() == 0 or self.registration.run_as != _current_user():
            raise SourceProtocolError("source requires its dedicated non-root service identity")
        self.process = subprocess.Popen(
            self.registration.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            close_fds=True, start_new_session=True)
        return self

    def __exit__(self, *_):
        if self.process is not None:
            try:
                os.killpg(self.process.pid, 15)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, 9)
                except ProcessLookupError:
                    pass
                self.process.wait()
            for stream in (self.process.stdin, self.process.stdout):
                if stream:
                    stream.close()

    def send(self, payload):
        encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        if len(encoded) > _MAX_MESSAGE:
            raise SourceProtocolError("request too large")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise SourceProtocolError("source timeout")
        try:
            self.process.stdin.write(encoded)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise SourceProtocolError("source disconnected") from exc

    def receive(self, request_id):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while True:
                if b"\n" in self.buffer:
                    line, _, rest = self.buffer.partition(b"\n")
                    self.buffer = bytearray(rest)
                    try:
                        message = json.loads(line)
                    except (ValueError, UnicodeDecodeError) as exc:
                        raise SourceProtocolError("invalid source JSON") from exc
                    if type(message) is not dict or message.get("jsonrpc") != "2.0":
                        raise SourceProtocolError("invalid JSON-RPC envelope")
                    if message.get("id") != request_id:
                        raise SourceProtocolError("unexpected response id")
                    if "error" in message:
                        raise SourceProtocolError("source returned JSON-RPC error")
                    if type(message.get("result")) is not dict:
                        raise SourceProtocolError("invalid source result")
                    return message["result"]
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise SourceProtocolError("source timeout")
                if not selector.select(remaining):
                    raise SourceProtocolError("source timeout")
                chunk = os.read(self.process.stdout.fileno(), 8192)
                if not chunk:
                    raise SourceProtocolError("source closed output")
                self.buffer.extend(chunk)
                if len(self.buffer) > _MAX_MESSAGE:
                    raise SourceProtocolError("source response too large")

    def request(self, request_id, method, params):
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return self.receive(request_id)

    def initialize(self):
        result = self.request(1, "initialize", {
            "protocolVersion": _PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "gway-source-adapter", "version": "1"}})
        if result.get("protocolVersion") != _PROTOCOL:
            raise SourceProtocolError("unsupported source protocol version")
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})


def _current_user():
    import pwd
    return pwd.getpwuid(os.geteuid()).pw_name


def _check_tool_list(result):
    tools = result.get("tools")
    if type(tools) is not list or len(tools) > 64:
        raise SourceProtocolError("invalid source tool list")
    for tool in tools:
        if type(tool) is not dict or type(tool.get("name")) is not str:
            raise SourceProtocolError("invalid source tool declaration")
    return tools


def list_source_tools(registration, timeout=10):
    with _Session(registration, timeout) as session:
        session.initialize()
        return _check_tool_list(session.request(2, "tools/list", {}))


def call_source_tool(registration, name, arguments, declared_tool, *, authorized_scope="read", timeout=10):
    """Execute only the currently declared tool under the caller's scope.

    Re-discovery in the same stdio session prevents a provider from changing
    its declaration between authorization and invocation.
    """
    if type(name) is not str or type(arguments) is not dict or type(declared_tool) is not dict:
        raise SourceProtocolError("invalid tool call")
    if authorized_scope not in ("read", "execute"):
        raise SourceProtocolError("invalid caller scope")
    if declared_tool.get("name") != name:
        raise SourceProtocolError("tool declaration mismatch")
    if required_scope(declared_tool) == "execute" and authorized_scope != "execute":
        raise SourceProtocolError("execution scope required")
    with _Session(registration, timeout) as session:
        session.initialize()
        current = _check_tool_list(session.request(2, "tools/list", {}))
        matching = [tool for tool in current if tool.get("name") == name]
        if len(matching) != 1 or matching[0] != declared_tool:
            raise SourceProtocolError("source tool changed since discovery")
        if required_scope(matching[0]) == "execute" and authorized_scope != "execute":
            raise SourceProtocolError("execution scope required")
        result = session.request(3, "tools/call", {"name": name, "arguments": arguments})
        if type(result.get("content")) is not list:
            raise SourceProtocolError("invalid tool result")
        return result
