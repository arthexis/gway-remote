# Executor identity provisioning contract — GWay Remote #617

This defines only **initial node-local identity selection**. The authorization
boundary stays unchanged: Watchtower authenticates node and OAuth scope;
`gway:read` cannot become `gway:execute`; no MCP request may choose a Unix
user or override a root-owned identity file.

## Single persistent policy

The existing format is deliberately retained:

```json
{"user":"existing-nonroot-login"}
```

Path: `/etc/gway-remote/executor-identity.json`. The policy and its parent
must be root-owned and not group/world-writable; symlinks, unknown users,
root UID, malformed/oversized JSON and ambiguous user records fail closed.
The configured `user` is the **executor**, not a transport credential, not
the Ansible `become` user and not the owner of every provider.

Precedence at provisioning, evaluated before executor changes:

1. An existing valid policy **wins**, even if a later installer is different.
   An explicit conflicting override is refused, **not** treated as permission
   to migrate.
2. If an old isolated executor/relay exists without a policy, preserve the
   legacy `gway-exec` identity and its history. Do not guess an operator.
3. Otherwise a nonempty explicit `executor_user` override selects an
   existing, validated non-root account.
4. Otherwise use the verified original non-root installer account.
5. If no verified installer or override exists, fail before provisioning.

The Python selector is shared: standalone `gway_remote/wireguard_satellite.py`
contains `resolve_executor_user`, and `scripts/resolve-executor-user.py`
imports that same selector for Ansible. It does not dispatch jobs.

## Entrypoints

- **Bootstrap URL:** run with `sudo` so `SUDO_USER` and `SUDO_UID`
  identify the original installer. They must resolve to the same existing
  non-root passwd record. For an unattended root-only bootstrap, explicitly
  pass `--executor-user EXISTING_USER` to the downloaded shell script
  (for example, `sudo sh -s -- --executor-user operator`). The stage-one
  script forwards this flag to its standalone client. No account is created
  for the override and no credential material is copied.
- **Normal Ansible deployment:** `./deploy.sh` refuses root and passes the
  actual invoking `id -un` as `gway_remote_runner_user`. The role resolves
  the same identity before preparing the dormant `gway-exec` account.
  For private executor state, Ansible uses the account's actual primary GID,
  which need not have the same name as the login.
  For an explicitly root-driven Ansible install, supply the intended
  existing CLI runner with `gway_remote_runner_user` and a separate explicit
  `gway_remote_executor_override`; never infer the become user. The override
  affects only a fresh identity policy, never an already installed node.
- **Upgrade:** do not change the selected identity or ledgers. Bootstrap
  creates a root-owned policy only if absent. Ansible keeps the existing
  guarded SSH relay, user manager checks, ledger-drain check, and existing
  byte-for-byte rescue path. This change is **not** an identity migration tool.

## Security and operational caveats

The selected Unix user can access **its own** home, workspace, processes and
whatever privileges the OS already grants. Selecting a sudo-capable operator
increases the authority of execute-scoped commands compared to the locked
`gway-exec` account; it must be an explicit provisioning security decision.
No new sudo grants, host-key bypass, user switching per MCP request, secret
copying, private-home permission relaxation, provider owner impersonation,
or cross-node routing permissions are introduced here.

The SSH ingress remains `gway-relay`; Ansible `become` retains its separate
administrative role. A provider with a different owner still needs a reviewed
narrow local handoff. In particular, **this does not migrate gway-004** or
resolve AgentOps #96's federated read access by itself. That field cutover,
runtime acceptance and #615 completion are separate authorizations.

## Review gates

PR-only CI should cover fresh installs, the trusted sudo origin, explicit
override, unknown/root/ambiguous accounts, unattended root-only failures,
preservation of valid policy, legacy state/relay, idempotent persistence,
negative node/scope routing (existing tests), and unchanged relay rollback
behaviour. A successful CI result is **not** evidence of field acceptance.
Merge does not authorize live-node executor migration, AgentOps dispatch, or
permission changes. Existing main-branch automation is independent of a
separately reviewed field cutover.
