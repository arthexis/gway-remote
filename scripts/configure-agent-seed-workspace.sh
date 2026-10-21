#!/bin/sh
# Explicit opt-in: configure Agent Ops seed reference for Gway Remote API.
# Never copies Codex credentials, changes the live seed, or restarts a service.
set -eu
[ "$(id -u)" -ne 0 ] || { echo "Run as operator, not root" >&2; exit 1; }
command -v python3 >/dev/null
ROOT="${GWAY_AGENT_WORKSPACE_ROOT:-$HOME/.local/share/gway-agent-ops/workspaces}"
SEED="${GWAY_AGENT_SEED_CODEX_HOME:-$HOME/.codex}"
CONFIG="$HOME/.config/gway-remote/mobile-api.env"
[ -f "$CONFIG" ] && [ ! -L "$CONFIG" ] || { echo "Install mobile API first" >&2; exit 1; }
python3 - "$ROOT" "$SEED" "$CONFIG" <<'PY'
import os
import pathlib
import stat
import sys
root, seed, config = map(pathlib.Path, sys.argv[1:])
if not root.is_absolute() or not seed.is_absolute():
    raise SystemExit("Workspace and seed paths must be absolute")
for path in (seed,):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise SystemExit("Seed home must be a private real directory owned by operator")
for name in ("config.toml", "auth.json"):
    path = seed / name
    if path.is_symlink() or not path.is_file():
        raise SystemExit("Seed is missing a regular " + name)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise SystemExit("Seed file permissions are unsafe: " + name)
if root.is_symlink():
    raise SystemExit("Workspace cannot be a symlink")
root.mkdir(parents=True, exist_ok=True, mode=0o700)
info = root.lstat()
if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
    raise SystemExit("Workspace ownership or permissions are unsafe")
lines = config.read_text().splitlines()
keys = ("GWAY_AGENT_WORKSPACE_ROOT", "GWAY_AGENT_SEED_CODEX_HOME")
lines = [line for line in lines if not any(line.startswith(key + "=") for key in keys)]
for key, value in zip(keys, (root, seed)):
    if any(c.isspace() or c in "#'\"\\$" for c in str(value)):
        raise SystemExit("Unsupported whitespace/shell characters in path")
    lines.append(f"{key}={value}")
import tempfile
fd, name = tempfile.mkstemp(dir=config.parent, prefix=".mobile-api-env-")
try:
    with os.fdopen(fd, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    os.chmod(name, 0o600)
    os.replace(name, config)
finally:
    if os.path.exists(name):
        os.unlink(name)
print("Agent workspace configured; service restart intentionally not performed.")
print("Review and restart gway-remote-mobile-api.service through approved deployment.")
PY
