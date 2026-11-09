"""Pure, fail-closed validation for provider-owned deployment declarations.

The declaration is data, not an instruction to execute its path. Execution
requires separate node-local authorization and trusted file verification.
"""
import re
from pathlib import PurePosixPath

_SHA = re.compile(r"^[0-9a-f]{40}$")


def validate_deployment(value):
    if type(value) is not dict or set(value) != {"schema", "checkout", "runner", "revision"}:
        raise ValueError("invalid deployment declaration")
    if type(value["schema"]) is not int or value["schema"] != 1:
        raise ValueError("unsupported deployment schema")
    if type(value["revision"]) is not str or not _SHA.fullmatch(value["revision"]):
        raise ValueError("deployment revision must be pinned")
    for field in ("checkout", "runner"):
        path = value[field]
        if type(path) is not str or not path.startswith("/") or "\x00" in path:
            raise ValueError("invalid deployment path")
        if any(ch in path for ch in ";|&$\x60\n\r\t"):
            raise ValueError("unsafe deployment path characters")
        if str(PurePosixPath(path)) != path or ".." in path.split("/") or path == "/":
            raise ValueError("unsafe deployment path")
    if not value["runner"].startswith(value["checkout"].rstrip("/") + "/"):
        raise ValueError("deployment runner must belong to checkout")
    return value
