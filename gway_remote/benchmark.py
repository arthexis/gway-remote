"""Bounded authenticated benchmark echo and pure latency statistics."""
from math import ceil
from statistics import median
from time import perf_counter_ns

MAX_ECHO_BYTES = 4096


def echo(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"payload"}:
        raise ValueError("invalid_arguments")
    payload = arguments["payload"]
    if not isinstance(payload, str):
        raise ValueError("invalid_payload")
    size = len(payload.encode("utf-8"))
    if size > MAX_ECHO_BYTES:
        raise ValueError("invalid_payload")
    started = perf_counter_ns()
    result = {"payload": payload, "payload_bytes": size}
    result["processing_ns"] = max(0, perf_counter_ns() - started)
    return result


def summarize(samples_ns, failures=0):
    """Nearest-rank p95; all durations in monotonic nanoseconds."""
    if not isinstance(samples_ns, (list, tuple)) or len(samples_ns) > 10000:
        raise ValueError("invalid_samples")
    if type(failures) is not int or failures < 0:
        raise ValueError("invalid_failures")
    if any(type(x) is not int or x < 0 for x in samples_ns):
        raise ValueError("invalid_samples")
    ordered = sorted(samples_ns)
    if not ordered:
        return {"samples": 0, "failures": failures, "median_ns": None,
                "p95_ns": None, "min_ns": None, "max_ns": None}
    return {"samples": len(ordered), "failures": failures,
            "median_ns": median(ordered), "p95_ns": ordered[ceil(.95 * len(ordered)) - 1],
            "min_ns": ordered[0], "max_ns": ordered[-1]}
