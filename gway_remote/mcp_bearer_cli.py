"""Local bearer administration under the fixed credential-owner identity."""
import os
import pwd


AUTH_USER = "gway-mcp-auth"


class BearerAdminError(RuntimeError):
    """An operator-facing identity error, with no credential data."""


def assume_auth_identity():
    """Drop root privileges before opening the bearer registry.

    No subprocess, shell, environment-selected user or remote execution is used.
    The regular auth owner may call directly; other users must use sudo.
    """
    try:
        account = pwd.getpwnam(AUTH_USER)
    except KeyError:
        raise BearerAdminError(
            "MCP auth account is not provisioned on this host; run on the Watchtower host") from None
    except OSError:
        raise BearerAdminError("could not look up the MCP auth account") from None
    if account.pw_uid <= 0 or account.pw_gid <= 0:
        raise BearerAdminError("MCP auth account must have a non-root UID and primary group")
    if os.geteuid() == account.pw_uid:
        return
    if os.geteuid() != 0:
        raise BearerAdminError("run sudo gway-remote bearer on the Watchtower host")
    try:
        # With effective UID zero, setuid/setgid also replace saved IDs on Linux.
        # Remove root's supplementary groups before changing either identity.
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
    except OSError:
        raise BearerAdminError("could not switch to the MCP auth account") from None
    if (os.getuid() != account.pw_uid or os.geteuid() != account.pw_uid
            or os.getgid() != account.pw_gid or os.getegid() != account.pw_gid):
        raise BearerAdminError("MCP auth identity verification failed")
