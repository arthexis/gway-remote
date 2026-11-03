"""Optional, read-only local RTC and ambient-temperature observations.

No device is mandatory for GWay Remote health or deployment. Linux owns
RTC synchronization; this module never configures, reads raw I2C, or writes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import platform
import re
import shutil

SYS_RTC = Path("/sys/class/rtc")
SYS_I2C = Path("/sys/bus/i2c/devices")
_TEMP = re.compile(r"-?[0-9]{1,7}(?:\.[0-9]+)?\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_TIME = re.compile(r"\d{2}:\d{2}:\d{2}\Z")


def _read(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="ascii").strip().rstrip("\x00")
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


def _integer(path: Path) -> int | None:
    raw = _read(path)
    if raw is None or not raw.isascii() or not raw.isdecimal():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _memory(meminfo: Path) -> dict:
    values = {}
    try:
        for line in meminfo.read_text(encoding="ascii").splitlines():
            key, sep, raw = line.partition(":")
            if sep and key in {"MemTotal", "MemAvailable", "MemFree"}:
                parts = raw.split()
                if len(parts) == 2 and parts[0].isascii() and parts[0].isdecimal() and parts[1] == "kB":
                    values[key] = int(parts[0]) * 1024
    except (OSError, ValueError, UnicodeError):
        pass
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    return {"total_bytes": total, "available_bytes": available,
            "used_percent": round(100 * (total - available) / total, 1)
            if total and available is not None and available <= total else None}


def _uptime(path: Path) -> float | None:
    raw = _read(path)
    try:
        number = float(raw.split()[0]) if raw else None
        return round(number, 1) if number is not None and 0 <= number < 1e12 else None
    except (IndexError, TypeError, ValueError, OverflowError):
        return None


def _soc_temperature(thermal_root: Path) -> float | None:
    try:
        zones = sorted(thermal_root.glob("thermal_zone*/temp"))
    except (OSError, ValueError):
        zones = []
    for path in zones[:16]:
        raw = _integer(path)
        if raw is not None and -55000 <= raw <= 125000:
            return round(raw / 1000, 3)
    return None


def _disk(root: Path) -> dict:
    try:
        usage = shutil.disk_usage(root)
    except (OSError, ValueError):
        return {"total_bytes": None, "free_bytes": None, "used_percent": None}
    return {"total_bytes": usage.total, "free_bytes": usage.free,
            "used_percent": round(100 * (usage.total - usage.free) / usage.total, 1)
            if usage.total else None}


def _host(*, meminfo: Path, uptime: Path, thermal_root: Path,
          cpu_freq: Path, model: Path, disk_root: Path) -> dict:
    raw_freq = _integer(cpu_freq)
    return {"model": _read(model), "architecture": platform.machine(),
            "cpu_count": os.cpu_count(), "cpu_frequency_mhz":
            round(raw_freq / 1000, 1) if raw_freq is not None else None,
            "cpu_temperature_c": _soc_temperature(thermal_root),
            "memory": _memory(meminfo), "uptime_seconds": _uptime(uptime),
            "root_filesystem": _disk(disk_root)}


def inspect(*, rtc_root: Path = SYS_RTC, i2c_root: Path = SYS_I2C,
            meminfo: Path = Path("/proc/meminfo"), uptime: Path = Path("/proc/uptime"),
            thermal_root: Path = Path("/sys/class/thermal"),
            cpu_freq: Path = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"),
            model: Path = Path("/sys/firmware/devicetree/base/model"),
            disk_root: Path = Path("/")) -> dict:
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
            "ambient_temperature": ambient,
            "host": _host(meminfo=meminfo, uptime=uptime, thermal_root=thermal_root,
                          cpu_freq=cpu_freq, model=model, disk_root=disk_root)}


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
    host = report["host"]
    lines += [f"Model: {host['model'] or 'unavailable'}",
              f"CPU: {host['architecture']} x{host['cpu_count'] or '?'} "
              f"{host['cpu_frequency_mhz'] if host['cpu_frequency_mhz'] is not None else '?'} MHz",
              f"SoC: {host['cpu_temperature_c'] if host['cpu_temperature_c'] is not None else '?'} C",
              f"RAM: {host['memory']['used_percent'] if host['memory']['used_percent'] is not None else '?'}% "
              f"of {host['memory']['total_bytes'] if host['memory']['total_bytes'] is not None else '?'} bytes",
              f"Uptime: {host['uptime_seconds'] if host['uptime_seconds'] is not None else '?'} s",
              f"Root disk: {host['root_filesystem']['used_percent'] if host['root_filesystem']['used_percent'] is not None else '?'}%"]
    return "\n".join(lines)
