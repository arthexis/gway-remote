# Federated MCP manifests: owner-only lifecycle

The authoritative installed provider registry on each node is
`/etc/gway-mcp-providers/<source_id>.json`. A provider's **own** reviewed
installer publishes, upgrades or removes its manifest atomically. GWay Remote
reads and validates these files and obtains each provider's tool catalog
with MCP `tools/list`; Watchtower authenticates and routes the resulting
federated tools and preserves their read/execute scopes.

## What changed

Previously the GWay Remote Ansible MCP runtime playbook ran
`scripts/converge-mcp-manifests.py` on **every** Remote deployment. That
migration tool replaced provider-owned manifests using registrations from
the old `/etc/gway-mcp-gateway/sources.json` and published or deleted
`agentops.json` based on the AgentOps release pointer. This could roll an
Odoo manifest back to an obsolete SHA while leaving Odoo's actual
`/opt/odoo-gelectriic/current` release untouched.

The deployment playbook **no longer calls** that tool. The legacy command
now exits nonzero with a retirement message **without accessing or mutating
provider manifests**; obsolete automation must be corrected instead of
silently reintroducing a stale registry. There is no replacement manifest
writer inside Remote's deployment. The playbook continues to verify that
the root-controlled installed provider directory is discoverable.

The pinned legacy `sources.json` policy and its environment settings are
retained for compatibility with older non-federated MCP backend paths;
they are **not** an installation source of truth and **must not** recreate,
update or delete node-owned provider manifests. Their eventual removal
requires a separate review of legacy consumers and is not needed for this
fix. In particular, AgentOps is responsible for its own `agentops.json`
lifecycle, as Odoo is for `odoo.json`.

## Safety and operational acceptance

- Keep the root-owned, non-symlink, non-group/other-writable manifest
  validation in `mcp_installed_providers.discover_installed_providers`.
  Executable trust checks and source-tool read/execute authorization remain
  unchanged. No per-tool Watchtower allowlist or extra enrollment approval.
- An Odoo installer may republish **only** its own `odoo.json`; a Remote
  deployment may only **read** it. No cross-provider write/delete and no
  reconstruction from a stale `sources.json` registration.
- Repeated Remote deployments (including unchanged revisions) must leave
  each valid `odoo.json` and `agentops.json` **bytes, inode and mtime**
  unchanged. Offline tests also execute the obsolete migration entrypoint
  twice and confirm it cannot overwrite, delete or resurrect either provider.
- After merge and an independently authorized automatic deployment, verify
  Remote's deployment result, Odoo `current` and installed manifest revision,
  `is-installed`, and live CLI/MCP search parity. If Odoo's manifest was
  already overwritten before this fix, **do not edit it from Remote**:
  the Odoo-owned installer must recover it under a separate authorization.
- The Odoo historical `previous` release lacking the quotation-search
  helper remains **not** an eligible rollback target. Fix-forward is a
  separate operational decision; this patch neither changes Odoo nor
  alters production credentials, ACLs or service identity.

Related: GWay Remote issues #474 and #487, and
`arthexis/odoo-gelectriic` PR #48.
