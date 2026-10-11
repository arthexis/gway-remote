"""Lightweight, side-effect-free timing probe for mobile benchmarks."""
from time import perf_counter_ns

MAX_ECHO_BYTES = 4096


def echo(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"payload"}:
        raise ValueError("invalid_arguments")
    payload = arguments["payload"]
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_ECHO_BYTES:
        raise ValueError("invalid_payload")
    started = perf_counter_ns()
    result = {"payload": payload, "payload_bytes": len(payload.encode("utf-8"))}
    result["processing_ns"] = perf_counter_ns() - started
    return result
