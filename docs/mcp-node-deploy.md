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

`workspace_inspect` is mapped to `workspace.inspect` with `gway:read` in
the authenticated, signed bridge envelope. Only `node` and `repository`
are accepted as arguments; clients cannot supply a checkout path, command or
environment. Watchtower must use a **separate, pinned read transport**; it
cannot silently reuse its execute transport. Request ID, node, repository and
signed reply are checked before returning a result.

The node-side `GWAY_WORKSPACE_INSPECT_CONFIG` must independently permit the
repository and map it to an absolute local checkout. Missing/unsafe
configuration, missing pinned read transport, wrong node, stale/forged reply or
SSH failure is rejected without fallback to an arbitrary local directory or
shell. The startup interfaces accept an explicitly injected
`read_transport`; the current gateway `main()` does **not** provision that
transport or a separate read-only SSH credential. Therefore **workspace
inspection remains unavailable in the default production bootstrap**.
Acceptance of offline wiring and security tests is not evidence of a live
read-enabled node.

The existing `node_file_download`/`file.read` contract is independent:
its fixed reader, correlated replies and node-local sudo isolation remain
unchanged by this integration.

## Rollout and acceptance boundary

No node installation, privilege migration, Watchtower configuration, release
activation, or application deployment is performed by accepting this PR.
Before production use, independently provision and attest the read-only SSH
identity, configure the node allowlist, validate provider manifests and
deployed receipts, then verify actual end-to-end results. Do not activate
`workspace_inspect` by reusing execute SSH credentials or local workspace
environment variables.

For `arthexis/odoo-gelectriic`, deployment remains repository-owned and
independent of this broker. A future trusted, root-owned installed-release
receipt must bind repository, installed 40-character revision, release path,
manifest digest, timestamp and successful active-link verification. Until
that separate adapter exists, report `installed_sha=unknown`; neither Git
HEAD nor a `current` symlink establishes the installed release.
