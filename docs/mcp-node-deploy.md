# MCP node deployment and read-only workspace inspection

This document describes the **integration branch** contract, not a completed
production rollout. The existing MCP names `node_deploy_preview`,
`node_deploy`, `node_deploy_status` and `workspace_inspect` remain stable.

## Deployment authorization (integration #534)

An enabled, independently attested node and an installed provider declaration
are both required. The provider's trusted manifest supplies the application,
checkout, runner and pinned 40-character revision; the MCP caller supplies
**none** of those filesystem paths or commands.

- `node_deploy_preview` (`gway:read`): verifies current Watchtower eligibility,
  pinned SSH node identity and a correlated node declaration. The caller's
  optional `revision` is `main` only. The response returns the installed
  declaration's pinned revision, not proof of a deployed application release.
- `node_deploy` (`gway:execute`): validates the OAuth execution principal,
  node eligibility, application and 32-character request ID; persists an
  idempotent, principal- and host-key-bound ledger claim before dispatch. The
  node-local executor checks the currently installed declaration/revision
  again, creates a durable receipt, then launches only the declared runner as
  the configured non-root identity. A missing acknowledgment is **uncertain**,
  never an invitation to dispatch the same ID again.
- `node_deploy_status` (`gway:execute`): reads the existing request's
  correlated node receipt. A caller may not use another principal's ID, change
  the application/revision, or treat an unverified response as success.

The request carries `node`, `application`, optional `revision="main"`,
and a server-reconciled `request_id` for start/status. It carries no shell
arguments, sudo target, systemd unit, checkout path or arbitrary SHA. The old
privileged `gway-remote-deploy.service` path and its dedicated sudo grant are
**retired** in the integration. A provider without a valid installed
declaration is ineligible even if its repository exists.

The node broker uses a private operator-owned receipt directory, exact
declaration validation, atomic receipt writes and a bounded worker. Receipt
states and Git checkout HEAD must not be presented as proof that a particular
application release is installed. The integration does not implement a general
rollback of application releases; its Ansible executor identity cutover has a
separate verified atomic SSH/sudoers/identity compensation path.

## Read-only workspace inspection (integration #538)

`workspace_inspect` maps to `workspace.inspect` with the existing
`gway:read` OAuth scope and authenticated bridge envelope. Like federated
`provider_read_call` and `file.read`, it uses the **same already configured
Watchtower→node pinned SSH transport** (`execution.relay.transport`).
It does not need a new SSH account, private key, bearer credential, approval,
transport selector, or independent read session. The application operation
determines whether a call is read-only; no SSH identity is switched by scope.

The gateway verifies the existing OAuth bearer and node authorization before
dispatch; the node protocol accepts only `node`, `repository` and a
server-generated correlated request ID for this operation. It never accepts
caller-provided checkout paths or arbitrary commands. The node-local
`GWAY_WORKSPACE_INSPECT_CONFIG` allowlist independently restricts repositories
to trusted local checkout paths. Missing transport, disabled execute-service
transport initialization, unsafe/missing allowlist, wrong node, forged reply or
SSH failure fails closed. This uses an *existing internal transport*, not an
additional user approval.

The gateway must never impersonate a node by using a Watchtower-local
workspace environment fallback. Existing `node_file_download`/`file.read`
reader isolation, limits and correlation are unchanged.

## Rollout and acceptance boundary

No node installation, new credential, privilege migration, Watchtower service
restart, release activation, or application deployment is performed by merging
this code. An already configured and attested node SSH relay can be used by
`workspace_inspect`; live operation additionally requires the node-local
allowlist to be present. Offline CI alone does not prove that allowlist or
node runtime exists. Do not enable access to new nodes implicitly.

For `arthexis/odoo-gelectriic`, deployment remains repository-owned and
independent of this broker. A future trusted, root-owned installed-release
receipt must bind repository, installed 40-character revision, release path,
manifest digest, timestamp and successful active-link verification. Until
that separate adapter exists, report `installed_sha=unknown`; neither Git
HEAD nor a `current` symlink establishes the installed release.
