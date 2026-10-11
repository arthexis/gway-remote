"""Explicit, read-only operations available to the mobile HTTP adapter."""
from .csms_health import csms_probe
from .status import status

OPERATIONS = {
    "probe-csms": csms_probe,
    "status": status,
}


def commands():
    return [{"name": name, "arguments": {}, "read_only": True}
            for name in OPERATIONS]


def execute(name, arguments):
    if not isinstance(name, str) or name not in OPERATIONS:
        raise ValueError("unknown_command")
    if not isinstance(arguments, dict) or arguments:
        raise ValueError("invalid_arguments")
    return OPERATIONS[name]()
