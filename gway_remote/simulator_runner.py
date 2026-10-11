"""Explicit, single-run simulator lifecycle for the mobile API.

No shell, arbitrary CLI arguments, daemon, or remote process execution.
"""
import fcntl
import ipaddress
import math
import time
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import uuid

from .simulator_network import _networks, _on_link

STATE_DIR = Path.home() / ".local/state/gway-remote/simulator"
SCENARIOS = {"boot", "charge", "remote", "battery"}
MAX_OUTPUT = 32768


def _identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        return fields[19] if fields[0] != "Z" else None
    except (OSError, IndexError):
        return None


def _read():
    try:
        return json.loads((STATE_DIR / "run.json").read_text())
    except (OSError, ValueError):
        return None


def _alive(run):
    if not isinstance(run, dict) or type(run.get("pid")) is not int:
        return False
    identity = _identity(run["pid"])
    return identity is not None and identity == run.get("identity")


def _lock():
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    stream = (STATE_DIR / "lock").open("a+")
    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    return stream


def _status():
    run = _read()
    if not run:
        return {"state": "idle"}
    active = _alive(run)
    state = ("stopping" if run.get("stopping") else "running") if active else "stopped"
    result = {"state": state, "pid": run["pid"],
              "scenario": run["scenario"], "target": run["target"]}
    if not active:
        if run.get("run_id"):
            try:
                exit_record = json.loads((STATE_DIR / ("exit-" + run["run_id"] + ".json")).read_text())
                run["exit_code"] = exit_record["exit_code"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
        result["outcome"] = "unknown"
        if run.get("exit_code") is not None:
            result["exit_code"] = run["exit_code"]
            result["outcome"] = "completed" if run["exit_code"] == 0 else "failed"
    return result


def status(arguments):
    if arguments != {}:
        raise ValueError("invalid_arguments")
    with _lock():
        return _status()


def start(arguments):
    if not isinstance(arguments, dict) or set(arguments) - {
            "host", "port", "cp", "scenario", "power", "duration", "connector",
            "rfid", "connectors", "meter_interval", "battery_kwh", "soc", "seed"}:
        raise ValueError("invalid_arguments")
    host, port = arguments.get("host"), arguments.get("port", 9000)
    cp, scenario = arguments.get("cp", "SIM001"), arguments.get("scenario", "boot")
    # Local CSMS testing is explicitly permitted; other targets stay on eth0.
    local_target = False
    if isinstance(host, str):
        try:
            local_target = ipaddress.ip_address(host) == ipaddress.IPv4Address("127.0.0.1")
        except ValueError:
            pass
    if not local_target and (not isinstance(host, str) or not _on_link(host, _networks()[1])):
        raise ValueError("target_must_be_on_wired_subnet")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid_port")
    if not isinstance(cp, str) or not 1 <= len(cp) <= 32 or not all(
            c.isascii() and (c.isalnum() or c in "_-") for c in cp):
        raise ValueError("invalid_cp")
    if scenario not in SCENARIOS:
        raise ValueError("invalid_scenario")
    args = ["ocpp-simulator", "run", "--cp", cp, "--url", f"ws://{host}:{port}/{cp}"]
    options = {
        "power": ("--power", (int, float), 0.1, 100),
        "duration": ("--duration", int, 1, 86400),
        "connector": ("--connector", int, 1, 16),
        "connectors": ("--connectors", int, 1, 16),
        "meter_interval": ("--meter-interval", int, 1, 3600),
        "battery_kwh": ("--battery-kwh", (int, float), 1, 300),
        "soc": ("--soc", (int, float), 0, 100),
        "seed": ("--seed", int, 0, 2147483647),
    }
    permitted = {
        "boot": set(), "charge": {"power", "duration", "connector", "rfid", "meter_interval"},
        "remote": {"power", "connectors", "meter_interval"},
        "battery": {"power", "connectors", "meter_interval", "battery_kwh", "soc", "seed"},
    }[scenario]
    if set(arguments) - {"host", "port", "cp", "scenario"} - permitted:
        raise ValueError("invalid_scenario_parameters")
    if scenario == "charge":
        args += ["--connector", str(arguments.get("connector", 1))]
        args += ["--duration", str(arguments.get("duration", 60))]
    elif scenario in ("remote", "battery"):
        args += ["--remote"]
    for key, (flag, types, minimum, maximum) in options.items():
        if key not in arguments or (scenario == "charge" and key in ("connector", "duration")):
            continue
        value = arguments[key]
        if isinstance(value, bool) or not isinstance(value, types) or not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError("invalid_" + key)
        args += [flag, str(value)]
    if scenario == "charge":
        for key, lo, hi in (("connector", 1, 16), ("duration", 1, 86400)):
            value = arguments.get(key, 1 if key == "connector" else 60)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError("invalid_" + key)
        rfid = arguments.get("rfid", "SIMTEST")
        if not isinstance(rfid, str) or not 1 <= len(rfid) <= 20 or not rfid.isascii() or not rfid.isalnum():
            raise ValueError("invalid_rfid")
        args += ["--rfid", rfid]
    executable = shutil.which("ocpp-simulator") or str(Path.home() / ".local/bin/ocpp-simulator")
    if not Path(executable).is_file():
        raise RuntimeError("simulator_not_installed")
    args[0] = executable
    with _lock():
        if _status()["state"] in ("running", "stopping"):
            raise ValueError("simulator_already_running")
        run_id = uuid.uuid4().hex
        log = STATE_DIR / "output.log"
        with log.open("wb") as output:
            proc = subprocess.Popen([sys.executable, "-m", "gway_remote.simulator_exit_monitor",
                                     str(STATE_DIR), run_id, *args],
                                    stdin=subprocess.DEVNULL, stdout=output,
                                    stderr=subprocess.STDOUT, start_new_session=True,
                                    close_fds=True)
        identity = _identity(proc.pid)
        if identity is None:
            raise RuntimeError("simulator_start_failed")
        record = {"pid": proc.pid, "identity": identity, "run_id": run_id, "scenario": scenario,
                  "target": f"{host}:{port}", "args": args[1:]}
        temp = STATE_DIR / "run.tmp"
        temp.write_text(json.dumps(record))
        os.replace(temp, STATE_DIR / "run.json")
        # Catch immediate argument/configuration failures before claiming success.
        time.sleep(0.15)
        if proc.poll() is not None:
            # The monitor's exit code is not the simulator's exit code.
            # Its per-run exit record is the only authoritative outcome.
            return {**_status(), "error": "simulator_exited_early"}
        return _status()


def stop(arguments):
    if arguments != {}:
        raise ValueError("invalid_arguments")
    with _lock():
        run = _read()
        if _alive(run):
            if run.get("stopping"):
                return _status()
            # Verify identity again immediately before signalling.
            if not _alive(run):
                return _status()
            try:
                os.kill(run["pid"], signal.SIGTERM)
            except ProcessLookupError:
                return _status()
            run["stopping"] = True
            temp = STATE_DIR / "run.tmp"
            temp.write_text(json.dumps(run))
            os.replace(temp, STATE_DIR / "run.json")
            return _status()
        return _status()


def results(arguments):
    if arguments != {}:
        raise ValueError("invalid_arguments")
    with _lock():
        state = _status()
        try:
            with (STATE_DIR / "output.log").open("rb") as stream:
                stream.seek(0, 2)
                size = stream.tell()
                stream.seek(max(0, size - MAX_OUTPUT))
                output = stream.read().decode("utf-8", errors="replace")
        except OSError:
            size, output = 0, ""
        return {**state, "output": output, "truncated": size > MAX_OUTPUT}
