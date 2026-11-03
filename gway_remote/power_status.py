"""Best-effort Raspberry Pi power status via firmware throttling flags.

vcgencmd is optional. No sudo, writes, or impact on component health checks.
"""
from __future__ import annotations

import re
import subprocess

_FLAGS = (
    (0, "undervoltage_now"),
    (1, "frequency_capped_now"),
    (2, "throttled_now"),
    (3, "soft_temperature_limit_now"),
    (16, "undervoltage_occurred"),
    (17, "frequency_capped_occurred"),
    (18, "throttled_occurred"),
    (19, "soft_temperature_limit_occurred"),
)
_OUTPUT = re.compile(r"throttled=(0x[0-9a-fA-F]{1,8})\s*\Z")


def probe(*, runner=subprocess.run) -> dict:
    """Never fail status on missing/unsupported firmware utilities."""
    result = {"status": "unavailable", "raw": None,
              **{name: None for _, name in _FLAGS}}
    try:
        proc = runner(["vcgencmd", "get_throttled"],
                      capture_output=True, text=True, check=False, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return result
    if proc.returncode:
        return result
    match = _OUTPUT.fullmatch(proc.stdout.strip())
    if not match:
        return result
    bits = int(match.group(1), 16)
    result["raw"] = f"0x{bits:x}"
    result.update({name: bool(bits & (1 << bit)) for bit, name in _FLAGS})
    result["status"] = "warning" if bits & (0xF | 0xF0000) else "ok"
    return result


def format_power(value: dict) -> str:
    if value.get("status") == "unavailable":
        return "Power: unavailable (vcgencmd unsupported or absent)"
    active = [name for _, name in _FLAGS if name.endswith("_now") and value.get(name)]
    past = [name for _, name in _FLAGS if name.endswith("_occurred") and value.get(name)]
    return (f"Power: {value['status']} ({value['raw']}); "
            f"current={','.join(active) or 'none'}; "
            f"since_boot={','.join(past) or 'none'}")
