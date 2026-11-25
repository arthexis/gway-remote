# MCP node deployment and read-only workspace inspection

This document describes the **integration branch** contract, not a completed
production rollout. The existing MCP names `node_deploy_preview`,
`node_deploy`, `node_deploy_status` and `workspace_inspect` remain stable.

## Deployment authorization (integration #534)

An enabled, independently attested node and an installed provider declaration
are both required. The provider's trusted manifest supplies the application,
checkout, runner and pinned 40-character revision; the MCP caller supplies
**none** of those filesystem paths or commands.

- `node_deploy_discovery` (`gway:read`): reads the live provider declarations
  on the attested node, returning only canonical source IDs, fixed aliases,
  pinned target revisions and declaration status. `declared` does not prove
  runner availability or an installed application revision. Enrollment
  capability inventory is separate and is not live deployment discovery.
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

The code-owned aliases `gway-lcd-sound` and `gway-agent-ops` normalize to
`lcd_sound` and `agentops` before preview, request binding and status checks.
The provider installation revision and declared deployment target are distinct.
`main` selects the already installed target pin; it does not fetch or refresh it.
A provider-owned provisioning workflow must refresh and publish a verified pin
before a new request. Existing requests stay bound to their original pin.

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

## Provider ownership and applicability (#724)

The gway-001 audit identifies three currently authorized broker applications:
`repo` (existing), `lcd_sound` and `agentops`. The latter two register
their runner via root-controlled provider publication from clean detached
full-SHA checkouts owned by the existing installation user. No client-supplied
paths or fresh credentials are involved. Their provider repositories document
the staging and pin-refresh procedure. Existing declaration targets are retained
on ordinary provider republication; an explicit approved pin refresh is
required to change the desired target. Do not prune a referenced checkout.

`android` is part of GWay Remote's deployment, not a separate independently
authorized broker application. `ocpp` and `odoo` have separate service
deployment ownership and live operational constraints; `webos` has its
own device deployment flow. All four remain without broker declarations until
a separately reviewed revision-pinned runner and node authorization exist.
Runtime sidecars (for example AgentOps runtime metadata) are not applications.
Inventory and provider presence alone never confer deployment eligibility.

Sanitized failures include invalid/unknown application, disabled provider,
missing/invalid declaration, declaration drift, permission denied, missing
request and transport/protocol unavailability. A correlated run error is
reported without releasing or retrying an uncertain dispatch claim. Preview
and discovery do not change node state.

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
caller-provided checkout paths or arbitrary commands. The protocol's trusted hostname is the node identity. Checkout roots are
derived **only** from pre-existing, installed node-owned records:
root-provisioned MCP provider manifests with a deployment checkout, or the
existing AgentOps repository policy plus its registered workspace root. A
local Git origin must match the requested repository and the checkout must
be accessible, non-symlinked and non-world-writable. No new
`GWAY_WORKSPACE_NODE` or `GWAY_WORKSPACE_INSPECT_CONFIG` variable, allowlist
file, SSH identity, OAuth token, or additional approval is needed. No
filesystem-wide discovery or arbitrary caller-provided paths are permitted.

Unregistered, ambiguous, private/inaccessible or otherwise unsafe workspaces
return explicit `unknown` Git evidence; CI/deployment information also
remains `unknown` until independently verified, never inferred from local
checkout HEAD. The node executor is **not** elevated to the operator account
to inspect private AgentOps workspaces. Missing authenticated transport,
wrong node, malformed registration or SSH failure remains fail-closed.

The gateway must never impersonate a node by using a Watchtower-local
workspace environment fallback. Existing `node_file_download`/`file.read`
reader isolation, limits and correlation are unchanged.

## Rollout and acceptance boundary

No node installation, new credential, privilege migration, Watchtower service
restart, release activation, or application deployment is performed by merging
this code. An already configured and attested node SSH relay can be used by
`workspace_inspect`; live Git observations require an already registered and
readable checkout. In the gway-001 read-only field audit, existing provider
manifests did not contain deployment checkouts and the operator-private
AgentOps workspace was inaccessible to the isolated executor; therefore
this PR does not assert a live positive Git observation. Offline CI cannot
prove those runtime prerequisites. Do not enable access to new nodes implicitly.

For `arthexis/odoo-gelectriic`, deployment remains repository-owned and
independent of this broker. A future trusted, root-owned installed-release
receipt must bind repository, installed 40-character revision, release path,
manifest digest, timestamp and successful active-link verification. Until
that separate adapter exists, report `installed_sha=unknown`; neither Git
HEAD nor a `current` symlink establishes the installed release.
