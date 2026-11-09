# MCP deployment: one canonical node_deploy

The existing `node_deploy` and `node_deploy_status` MCP names are retained.
`node_deploy_preview` adds a **read-only** eligibility check.

## Initial enabled targets

- `gway-001` + `gway-remote`: existing, unchanged operator-owned systemd service.
- `gway-001` + `odoo-gelectriic`: a second **fixed** systemd service executes the existing generic Odoo Ansible CLI installation tasks. All business and quote data are explicitly excluded.
- All other node/application pairs: denied by default. This includes
  `gway-002`, pending its independently pinned attestation; there is no
  automatic trust-on-first-use.

These are actual installed recipe targets, **not** a claim that all enrolled
nodes support deployment. Additional nodes require an independently attested
transport, root-owned audited target recipe, associated sudo authorization,
receipt handling, and complete integration tests.

## Contract

```json
{"node":"gway-001","application":"odoo-gelectriic",
 "revision":"main","request_id":"0123456789abcdef0123456789abcdef"}
```

`revision` is optional and currently only `main` is supported by the
fixed-service transport. An arbitrary commit SHA is not accepted yet: the
existing service fast-forwards the approved operator checkout on `main`.
The request has **no** shell, path, service, or Ansible arguments.

- `node_deploy_preview`: `node`, `application`, optional `revision`.
  Confirms current identity and configured fixed recipe, does not execute.
- `node_deploy`: starts the fixed service using the existing bounded,
  authenticated, idempotent `node_exec` transport and returns its request ID.
- `node_deploy_status`: starts a read-only retrieval of that application's
  durable service receipt. Follow its returned request ID through `node_result`.

The service receipt reports service-level `running/succeeded/failed`, not
merely the exit code of `systemctl start --no-block`. A receipt can only be
trusted for the exact application and target. There is no generic remote
`sudo` or permission to execute an arbitrary playbook.

The Odoo deployment uses `ansible/roles/gway_remote/tasks/odoo-gelectriic.yml`
already exercised manually on `gway-001`. It checks a clean `main`
checkout, fast-forwards only, installs root-owned CLI binaries and validates
help without opening any customer quote. It does **not** run catalog apply.

## Rollout

Deploy the GWay Remote Ansible role on `gway-001` to install the fixed
Odoo unit and read-only receipt path; then roll out the Watchtower MCP
gateway so that its tool list advertises `node_deploy`,
`node_deploy_status` and `node_deploy_preview`. Reconnect/refresh the
ChatGPT plugin's discovered tools. Observe the service receipt after a
pilot and verify both the installed CLI hash and current Git revision.

This stage does **not** enable any non-attested node or integrate the
separate `manual_deploy_async` broker for arbitrary SHA jobs. The
fixed-service transport deliberately remains the authoritative, working
boundary; do not claim multi-node or immutable-SHA deployment until the
backend supports and tests it.

## Odoo independent deployment — current contract

The legacy fixed Odoo systemd deployment recipe described above has been
removed from the current `AuthorizedExecution.deployment_preview` allowlist.
It must **not** be re-enabled by this PR. Odoo owns its deployment through
`arthexis/odoo-gelectriic/deploy.sh` and local Ansible on `gway-001`.

The new `workspace_inspect` forced-protocol operation is strictly read-only:
its request contains only an attested node, a server-generated request ID,
and a repository name. The node's operator-owned
`GWAY_WORKSPACE_INSPECT_CONFIG` maps allowlisted repositories to absolute
checkout paths; Watchtower must not impersonate `gway-001` with a local
workspace environment variable. The private bridge must be supplied a
separate pinned `read_transport` by its trusted bootstrap. Absent that
transport it denies the request. No generic SSH or local fallback is allowed.

**Required installed-release receipt (not implemented here):** the Odoo
installer should publish an atomic, root-owned record containing repository,
40-character installed revision, release path under
`/opt/odoo-gelectriic/releases/<sha>`, manifest digest, observed timestamp,
and successful active-link/integrity verification. An authorized node-side
read-only adapter must verify owner, mode, non-symlink path, expected release
and digest on every read, and bind the response to the attested node and
request ID. A checkout HEAD or `current` symlink alone is **not** proof of
installed revision. Until that adapter is implemented and installed, report
`installed_sha=unknown`, never inferred from GitHub or checkout HEAD.

The current PR adds a dormant protocol path only; it does not provision
root-owned allowlists, trusted read transport or receipts in production.
