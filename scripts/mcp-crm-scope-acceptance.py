#!/usr/bin/env python3
"""Fixed, non-mutating CRM scope acceptance over live Watchtower MCP.

Use only existing, independently authorized OAuth access tokens, entered
locally through a non-echoing terminal. Never issue, refresh or revoke them.
No production write payload, node execution, redirect, or response logging.
"""
import getpass
import hmac
import json
import re
import ssl
import sys
import warnings
from urllib.error import HTTPError
from urllib.request import (
    HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener,
)

ENDPOINT = "https://remote.arthexis.com/mcp"
MAX_BYTES = 65536
WRITES = (
    "odoo__crm_opportunity_create",
    "odoo__crm_opportunity_update",
    "odoo__crm_opportunity_stage_move",
)
RECEIPT = "odoo__crm_receipt_status"
DIAGNOSTIC = "node_exec_diagnostic"
# Deliberately invalid CRM payload: no request_id, record ID, customer,
# or values. The provider rejects it before entering the commercial writer.
# Do not replace this with a real or synthetic valid write request.


class AcceptanceError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def call(token, name, args):
    if name in WRITES:
        if args != {}:
            raise AcceptanceError("unsafe_payload")
    elif name in (RECEIPT, DIAGNOSTIC):
        if set(args) != {"request_id"} or not re.fullmatch(
                r"[0-9a-f]{32}", args["request_id"]):
            raise AcceptanceError("invalid_request_id")
    else:
        raise AcceptanceError("unapproved_tool")
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "method": "tools/call",
                       "params": {"name": name, "arguments": args}}).encode()
    request = Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "MCP-Protocol-Version": "2025-03-26",
    })
    opener = build_opener(ProxyHandler({}), NoRedirect(),
                          HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=35) as response:
            raw = response.read(MAX_BYTES + 1)
            if response.status != 200 or len(raw) > MAX_BYTES:
                raise AcceptanceError("unexpected_response")
            payload = json.loads(raw)
            if payload.get("jsonrpc") != "2.0" or payload.get("id") != 1:
                raise AcceptanceError("invalid_rpc")
            result = payload.get("result")
            if not isinstance(result, dict):
                raise AcceptanceError("invalid_result")
            return 200, "", result
    except HTTPError as exc:
        try:
            return exc.code, exc.headers.get("WWW-Authenticate", ""), {}
        finally:
            exc.close()


def insufficient_scope(challenge):
    return ('scope="gway:execute"' in challenge
            and 'error="insufficient_scope"' in challenge)


def receipt_result(response, rid):
    status, _, result = response
    if status != 200 or result.get("isError"):
        raise AcceptanceError("receipt_read_failed")
    content = result.get("content", [])
    if len(content) != 1 or content[0].get("type") != "text":
        raise AcceptanceError("receipt_shape")
    receipt = json.loads(content[0]["text"])
    if (receipt.get("request_id") != rid
            or receipt.get("status") != "completed"
            or type(receipt.get("id")) is not int
            or receipt["id"] < 1):
        raise AcceptanceError("receipt_not_completed")
    return receipt


def check(read_token, execute_token, rid, *, invoke=call):
    if (not read_token or not execute_token
            or hmac.compare_digest(read_token, execute_token)):
        raise AcceptanceError("distinct_existing_credentials_required")
    for token in (read_token, execute_token):
        if len(token) > 4096 or any(c.isspace() for c in token):
            raise AcceptanceError("invalid_credential_format")
    if not re.fullmatch(r"[0-9a-f]{32}", rid):
        raise AcceptanceError("invalid_request_id")
    args = {"request_id": rid}
    read_receipt = receipt_result(invoke(read_token, RECEIPT, args), rid)
    # Builtin execute-scope control is strictly read-only: it inspects an
    # opaque diagnostic ID, never submits a command.
    control = {"request_id": "0" * 32}
    status, _, result = invoke(read_token, DIAGNOSTIC, control)
    meta = result.get("_meta", {})
    challenges = meta.get("mcp/www_authenticate", [])
    if (status != 200 or result.get("isError") is not True
            or not any(isinstance(c, str) and insufficient_scope(c)
                       for c in challenges)):
        raise AcceptanceError("read_control_not_denied")
    status, _, result = invoke(execute_token, DIAGNOSTIC, control)
    if status != 200 or result.get("isError") or not result.get("content"):
        raise AcceptanceError("execute_control_not_admitted")
    for name in WRITES:
        status, challenge, _ = invoke(read_token, name, {})
        # Unlike the builtin control, federation returns a real HTTP 401.
        if status != 401 or not insufficient_scope(challenge):
            raise AcceptanceError("crm_scope_denial_not_verified")
    if receipt_result(invoke(execute_token, RECEIPT, args), rid) != read_receipt:
        raise AcceptanceError("shared_receipt_mismatch")
    if receipt_result(invoke(read_token, RECEIPT, args), rid) != read_receipt:
        raise AcceptanceError("receipt_changed")
    return {"scope_isolation": "passed", "crm_denials": len(WRITES),
            "shared_receipt_read": "passed", "principal_ownership": "not_applicable",
            "mutation_payloads": 0}


def main():
    # Never fall back to echoed stdin, command arguments, or environment.
    if not sys.stdin.isatty() or not sys.stderr.isatty() or len(sys.argv) != 1:
        print("BLOCKED: protected interactive terminal required", file=sys.stderr)
        return 1
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            read_token = getpass.getpass("Existing read-only OAuth access token: ")
            execute_token = getpass.getpass("Existing execute OAuth access token: ")
            rid = getpass.getpass("Existing completed CRM receipt ID: ")
        print(json.dumps(check(read_token, execute_token, rid), sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt):
        # No raw exception, token, request, header or response text.
        print("BLOCKED: CRM scope acceptance not established", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
