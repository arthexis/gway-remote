"""Optional, read-only local RTC and ambient-temperature observations.

No device is mandatory for GWay Remote health or deployment. Linux owns
RTC synchronization; this module never configures, reads raw I2C, or writes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

SYS_RTC = Path("/sys/class/rtc")
SYS_I2C = Path("/sys/bus/i2c/devices")
_TEMP = re.compile(r"-?[0-9]{1,7}(?:\\.[0-9]+)?\\Z")
_DATE = re.compile(r"\\d{4}-\\d{2}-\\d{2}\\Z")
_TIME = re.compile(r"\\d{2}:\\d{2}:\\d{2}\\Z")


def _read(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError, ValueError):
        return None
    return value if value else None


def _rtc_entry(device: Path) -> dict:
    name = _read(device / "name")
    date, clock = _read(device / "date"), _read(device / "time")
    stamp = None
    if date and clock and _DATE.fullmatch(date) and _TIME.fullmatch(clock):
        try:
            stamp = datetime.fromisoformat(f"{date}T{clock}+00:00").isoformat()
        except ValueError:
            pass
    hctosys = _read(device / "hctosys")
    return {"device": device.name, "driver": name, "time_utc": stamp,
            "initialized_system_clock": hctosys == "1" if hctosys in {"0", "1"} else None}


def _ambient(i2c_root: Path) -> dict:
    """Use only the known DS3231 address; do not confuse Pi SoC with ambient."""
    device = i2c_root / "1-0068"
    try:
        candidates = sorted((device / "hwmon").glob("hwmon*/temp1_input"))
    except (OSError, ValueError):
        candidates = []
    for path in candidates[:8]:
        raw = _read(path)
        if raw is None or not _TEMP.fullmatch(raw):
            continue
        try:
            value = float(raw) / 1000
        except ValueError:
            continue
        # DS3231 measures ambient inside its own package, not CPU temperature.
        if -55 <= value <= 125:
            return {"status": "available", "celsius": round(value, 3),
                    "source": "ds3231-i2c-1-0068"}
    return {"status": "unavailable", "celsius": None, "source": None}


def inspect(*, rtc_root: Path = SYS_RTC, i2c_root: Path = SYS_I2C) -> dict:
    """Best-effort diagnostics; missing devices never turn into failures."""
    devices = []
    try:
        entries = sorted(rtc_root.glob("rtc*"))
    except (OSError, ValueError):
        entries = []
    for device in entries[:8]:
        if re.fullmatch(r"rtc[0-9]+", device.name):
            devices.append(_rtc_entry(device))
    ambient = _ambient(i2c_root)
    return {"schema": "gway-remote/hardware/v1",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "rtc": {"status": "available" if devices else "unavailable",
                    "devices": devices},
            "ambient_temperature": ambient}


def format_hardware(report: dict) -> str:
    lines = ["Optional local hardware (read-only)",
             f"RTC: {report['rtc']['status']}"]
    for rtc in report["rtc"]["devices"]:
        lines.append(f"  {rtc['device']}: {rtc['driver'] or 'unknown'} "
                     f"time={rtc['time_utc'] or 'unknown'} "
                     f"hctosys={rtc['initialized_system_clock']}")
    sensor = report["ambient_temperature"]
    lines.append("Ambient: " + (
        f"{sensor['celsius']} C ({sensor['source']})"
        if sensor["status"] == "available" else "unavailable"))
    return "\n".join(lines)
