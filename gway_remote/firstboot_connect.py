"""First-boot Raspberry Pi Connect activation for #682.

A small, standalone POSIX payload is injected into Raspberry Pi Imager's
cloud-init runcmd. This module never receives, prints or replaces auth.key.
The Imager-provided key is consumed by rpi-connect-signin.path itself.
"""
from __future__ import annotations

import re

USER_RE = re.compile(r"[a-z_][a-z0-9_-]{0,31}\Z")


def connect_firstboot_script(user: str) -> str:
    """Return an idempotent, secret-free first-boot script for a local account."""
    if not USER_RE.fullmatch(user) or user == "root":
        raise ValueError("invalid non-root installer")
    return """#!/bin/sh
set -eu
umask 077
TARGET_USER='""" + user + """'
log() { logger -t gway-connect-firstboot -- "$1" 2>/dev/null || :; }
if [ "$(id -u)" != 0 ]; then log 'requires_root'; exit 1; fi
if ! id "$TARGET_USER" >/dev/null 2>&1; then log 'installer_missing'; exit 1; fi
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
if [ -z "$TARGET_HOME" ] || [ ! -d "$TARGET_HOME" ]; then
    log 'home_missing'; exit 1
fi
if ! command -v loginctl >/dev/null 2>&1; then log 'logind_missing'; exit 1; fi

# Image customisation is authoritative for the key, packages and account.
# Never print or pass auth.key as a process argument; do not try to sign in.
SERVICE=''
PATH_UNIT=''
for base in /usr/lib/systemd/user /lib/systemd/user; do
    [ -f "$base/rpi-connect.service" ] && SERVICE="$base/rpi-connect.service"
    [ -f "$base/rpi-connect-signin.path" ] && PATH_UNIT="$base/rpi-connect-signin.path"
done
if [ -z "$SERVICE" ] || [ -z "$PATH_UNIT" ]; then
    log 'connect_units_unavailable'; exit 1
fi

# Do not rewrite a configuration made by Imager, only establish missing links.
USER_SYSTEMD="$TARGET_HOME/.config/systemd/user"
# Prevent a pre-existing symlink from redirecting root-owned writes.
for part in "$TARGET_HOME/.config" "$TARGET_HOME/.config/systemd" "$USER_SYSTEMD" "$USER_SYSTEMD/default.target.wants" "$USER_SYSTEMD/rpi-connect.service.wants"; do
    if [ -L "$part" ]; then log 'unsafe_user_config_symlink'; exit 1; fi
done
install -d -m 0700 "$USER_SYSTEMD/default.target.wants" "$USER_SYSTEMD/rpi-connect.service.wants"
if [ ! -e "$USER_SYSTEMD/default.target.wants/rpi-connect.service" ]; then
    ln -s "$SERVICE" "$USER_SYSTEMD/default.target.wants/rpi-connect.service"
fi
if [ ! -e "$USER_SYSTEMD/rpi-connect.service.wants/rpi-connect-signin.path" ]; then
    ln -s "$PATH_UNIT" "$USER_SYSTEMD/rpi-connect.service.wants/rpi-connect-signin.path"
fi
chown "$TARGET_USER" "$TARGET_HOME/.config" "$TARGET_HOME/.config/systemd" "$USER_SYSTEMD" "$USER_SYSTEMD/default.target.wants" "$USER_SYSTEMD/rpi-connect.service.wants"
loginctl enable-linger "$TARGET_USER"
if ! systemctl --user --machine="$TARGET_USER@.host" daemon-reload; then
    log 'user_manager_unavailable'; exit 1
fi
if ! systemctl --user --machine="$TARGET_USER@.host" start rpi-connect.service; then
    log 'connect_start_failed'; exit 1
fi
if ! systemctl --user --machine="$TARGET_USER@.host" start rpi-connect-signin.path; then
    log 'signin_path_start_failed'; exit 1
fi
log 'connect_services_started'
"""
