"""Explicit, read-only selector for ABB's dormant legacy executor account."""
import os
from pathlib import Path
import socket
import stat

from .node_exec_identity import validated_account
from .wireguard_satellite import read_executor_policy, resolve_executor_user


def resolve_abb_user(*, allow_empty_legacy=False, hostname=None,
                     policy=Path('/etc/gway-remote/executor-identity.json'),
                     legacy_state=Path('/var/lib/gway-exec'),
                     legacy_relay=Path('/etc/ssh/sshd_config.d/40-gway-exec-relay.conf'),
                     legacy_sudoers=Path('/etc/sudoers.d/gway-exec-relay')):
    if os.geteuid() != 0 or (hostname or socket.gethostname()) != 'ocpp-abb-1':
        raise PermissionError('ABB root-local provisioning only')
    try:
        return resolve_executor_user('ubuntu', 'ubuntu', policy=policy,
                                     legacy_state=legacy_state, legacy_relay=legacy_relay)
    except PermissionError:
        if not allow_empty_legacy or read_executor_policy(policy) is not None:
            raise
        if os.path.lexists(policy) or os.path.lexists(legacy_relay) or os.path.lexists(legacy_sudoers):
            raise PermissionError('existing executor authorization requires separate review')
        account = validated_account('gway-exec')
        info = legacy_state.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != account.pw_uid
                or info.st_gid != account.pw_gid or stat.S_IMODE(info.st_mode) != 0o700
                or any(legacy_state.iterdir())):
            raise PermissionError('legacy state is not an empty private directory')
        validated_account('ubuntu')
        return 'ubuntu'
