# Dedicated Watchtower inspection identity

This deployment requires an administrator to provision a dedicated SSH public key
for gway-001 and independently verify the Watchtower host key. It must not reuse
the bootstrap enrollment token or grant general SSH access.

## Watchtower-side permissions

Create a dedicated, non-login inspection account with read-only access to the
Watchtower enrollment ledger and its parent directory. The account must not be
in sudoers or the WireGuard administration group. Grant read/search permissions
only for the exact ledger and directory, including SQLite WAL/SHM when present,
using scoped ACLs or a dedicated read-only group.

Configure the public key in the account's authorized_keys with a forced command
running `python3 -m gway_remote.watchtower_inspection_command` and the
restrictions `restrict,no-pty,no-agent-forwarding,no-X11-forwarding,no-port-forwarding`.
The command reads `/etc/gway-remote/watchtower.json` and the ledger; configure
their read permissions for this account, but never grant write access. Ensure
the ledger snapshot uses SQLite read-only access and never performs migrations.

The SSH key should be generated and retained on gway-001; only its public
half is installed on Watchtower. The controller's SSH configuration must contain
a dedicated `Host watchtower-inspection` alias with `HostName gelectriic.com`,
`BatchMode yes`, `StrictHostKeyChecking yes`, `IdentitiesOnly yes`,
a dedicated `IdentityFile` and an independently pinned `UserKnownHostsFile`.
The configuration and private key should be owned by the controller service
account, mode 0600; their parent directory must not be group/other writable.

Do not deploy these permissions automatically until the actual Watchtower
ledger location, SSH account, service user and existing Bastion trust contract
are confirmed. Field acceptance must prove that a shell, arbitrary commands,
port forwarding and write operations are denied.

## gway-004

No GWay Remote installation or new tunnel is required for the read-only
systemd inspection. The existing SSH account must have permission to run
`systemctl show` without sudo. No privileged service actions are needed.
