# Node-specific Ansible audit

The reusable execution relay role accepts managed GWay hostnames and still
requires an explicit transport opt-in and relay public key. This does not grant
execution, prove enrollment or attestation, configure Watchtower, or deploy a
relay. Those remain separate operator-controlled steps.

The scan also identified existing node-specific configuration and workflows
that need separate, safety-reviewed migration before they can be generalized:

- `ansible/inventory/deployment.yml` declares actual fleet members and their
  distinct permissions. These names are inventory data, not reusable role defaults.
- `gway_remote/tasks/main.yml` reads controller policy from the canonical
  inventory, installs controller-specific webOS retry units, and scopes a
  separate satellite behavior. `node-exec-select.yml` protects the current
  operator file-reader cutover. Replacing these checks needs explicit per-node
  policy and compatibility tests to preserve deployed behavior.
- `playbooks/adopt-wireguard-peer.yml` embeds an existing managed-peer marker;
  changing it without a migration can duplicate or replace a live peer.
- `playbooks/mcp-source-policy-rollout.yml`,
  `playbooks/mcp-source-policy-backend.yml`,
  `playbooks/gway001-mcp-runtime.yml`, and `provision-mcp-file-exports.yml`
  are bounded single-node operational workflows. Generalizing them requires
  explicit target identity, authorization and rollback contracts.

These findings are not claims that the remaining Ansible is node-neutral.
