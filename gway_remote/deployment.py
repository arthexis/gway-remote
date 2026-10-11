"""Transactional mobile API deployment, with injectable side effects for testing."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import urllib.request


SERVICE = "gway-remote-mobile-api.service"
HEALTH_URL = "http://10.90.0.2:8765/api/v1/health"
EXECUTABLE = "/usr/local/bin/gway-remote"


def run(*args):
    subprocess.run(args, check=True)


def health(token, *, attempts=15, pause=time.sleep, request=urllib.request.urlopen):
    for index in range(attempts):
        try:
            req = urllib.request.Request(HEALTH_URL, headers={"Authorization": "Bearer " + token})
            with request(req, timeout=2) as response:
                data = json.load(response)
            if data == {"status": "ok", "api": "gway-remote/v1"}:
                return
        except (OSError, ValueError, KeyError):
            pass
        if index + 1 < attempts:
            pause(1)
    raise RuntimeError("Authenticated mobile API health check failed")


def deploy(*, token, install, execute=run, probe=health, executable=EXECUTABLE,
           runtime=None, backup_dir=None):
    if not token:
        raise ValueError("GWAY_REMOTE_API_TOKEN must be configured")
    runtime = pathlib.Path(runtime or f"/run/user/{os.getuid()}")
    if not (runtime / "bus").is_socket():
        raise RuntimeError("Systemd user bus unavailable")
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = str(runtime)
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime}/bus"
    executable = pathlib.Path(executable)
    if not executable.is_file():
        raise RuntimeError("Installed executable is missing")

    def systemctl(*args):
        execute("systemctl", "--user", *args)

    # The caller's environment is used by subprocess commands in the workflow.
    old_runtime = {key: os.environ.get(key) for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")}
    os.environ.update({key: env[key] for key in old_runtime})
    try:
        systemctl("is-active", "--quiet", SERVICE)
        with tempfile.TemporaryDirectory(dir=backup_dir) as temp:
            backup = pathlib.Path(temp) / "previous"
            shutil.copy2(executable, backup)
            changed = False
            try:
                changed = True
                install()
                systemctl("restart", SERVICE)
                systemctl("is-active", "--quiet", SERVICE)
                probe(token)
            except Exception as failure:
                if changed:
                    try:
                        shutil.copy2(backup, executable)
                        systemctl("restart", SERVICE)
                        systemctl("is-active", "--quiet", SERVICE)
                        probe(token)
                    except Exception as rollback_error:
                        raise RuntimeError(
                            f"Deployment failed ({failure}); rollback verification failed ({rollback_error})"
                        ) from failure
                raise
    finally:
        for key, value in old_runtime.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
