"""MCP stdio adapter for the operator-authorized local browser lease."""
import json
import sys
from .browser_contract import MAX, call, declarations, validate_request

def dispatch(method, params):
    if method == "initialize":
        return {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                "serverInfo": {"name": "gway-browser", "version": "1"}}
    if method == "tools/list":
        return {"tools": declarations()}
    if method == "tools/call":
        if type(params) is not dict or set(params) != {"name", "arguments"} or type(params["arguments"]) is not dict:
            raise ValueError("invalid_call")
        if "operation" in params["arguments"]:
            raise ValueError("invalid_arguments")
        req = validate_request({"operation": params["name"], **params["arguments"]})
        try:
            result = call(req)
        except (OSError, ValueError, EOFError):
            result = {"ok": False, "state": "unavailable"}
        return {"content": [{"type": "text", "text": json.dumps(result, separators=(",", ":"))}],
                "isError": not result["ok"]}
    raise ValueError("unsupported_method")

def main():
    while True:
        raw = sys.stdin.buffer.readline(MAX + 1)
        if not raw:
            return
        if len(raw) > MAX or not raw.endswith(b"\n"):
            return
        request_id = None
        try:
            msg = json.loads(raw)
            if type(msg) is not dict or msg.get("jsonrpc") != "2.0":
                raise ValueError("invalid_request")
            if "id" not in msg:
                continue
            request_id = msg["id"]
            response = {"result": dispatch(msg.get("method"), msg.get("params", {}))}
        except (ValueError, TypeError, KeyError):
            response = {"error": {"code": -32602, "message": "Invalid or unsupported browser request"}}
        print(json.dumps({"jsonrpc": "2.0", "id": request_id, **response}), flush=True)

if __name__ == "__main__":
    main()
