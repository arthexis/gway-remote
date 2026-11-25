# Canonical MCP node routing (#716)

## Modes and migration
Gateway-only configuration: GWAY_MCP_NODE_ROUTING is legacy (default),
canonical-with-aliases (staged acceptance), or canonical (alias retirement).
No provider contract or receiver transport is changed. Unknown modes fail startup.
The legacy mode is the immediate rollback; do not edit the running production
environment as part of stage 1.

Canonical tools take a gateway-owned node string. Existing reads without node
are pinned to gway-001 if it offers the operation; no implicit selection of
another node. Canonical execute requires explicit node, even for singletons.
Temporary qualified aliases remain pinned to their original node (explicit
conflicting node rejected), including their legacy execute calling convention.
Clients must migrate execute calls before activation. No auto-retry across nodes.
A provider-owned node argument or mismatching contract fails discovery closed.
Catalog inspection lists nodes and legacy_alias; source status groups canonical
operations by actual source/node without counting aliases.

## Isolated acceptance
On gway-001, use an isolated checkout at the exact PR SHA, no service install,
no production secrets or registry, ephemeral localhost port, temporary SQLite
credential registry and synthetic node transport. Run:
    python3 -m unittest tests.mobile.test_mcp_canonical_routing_http tests.test_mcp_node_routing -v
Check read token routes to each mock node; no-node legacy read stays on 001;
wrong alias target, unknown/offline node, read token on write, missing execute
node denied without invocation; execute token dispatches only to explicit
mock target; catalog nodes and scope consistent; canonical-only removes aliases.
No real provider calls or charger traffic. Shut down the loopback server and
remove temp registry (test handles cleanup). Record exact SHA and CI evidence.

## Consumer audit
Repository search found qualified AgentOps names in old docs/tests, no
literal qualified names in Android, scripts, deploy or runtime callers.
External MCP clients, saved prompts, automations and dynamic consumers must
be inventoried before opting production into canonical-with-aliases.
For example agentops__submit now needs node="gway-001"; old qualified 004
aliases remain temporarily. OCPP tools use node="ocpp-abb-1" only after stage 2.

## Pre-rollout review and reversible activation

Evidence 2026-11-24 (Monterrey): Watchtower runtime a3ec9811a38c,
gateway/link active, pinned nodes 001/002/004/005, no routing override.
Live catalog 133 names, 16 qualified 004 aliases, five read-only OCPP
tools on 001, none on ABB. Real read-only AgentOps status on 001/004
and OCPP charger_list succeeded. Isolated acceptance at de9f4fd used
a guarded relay adapter, not production SSH credentials.
ProviderTransport, CheckedNodeTransport, SSHTransport and receiver
wire protocol are unchanged in this PR. They enforce pinned node,
current enrollment/eligibility, host-key verification, correlated
response identity and live tool classification. Do not copy private
SSH material or run execution smoke as a read-only test.

### Known consumer inventory
- Android, scripts, deploy and runtime: no literal old AgentOps calls
  found. Organization indexed searches for qualified names, submit,
  schedule and catalog inspection found no external call sites.
  ocpp-csms docs describe charger_list (legacy read remains compatible).
- ChatGPT automation inventory: 25 visible, four active; none of the
  four active prompts contain federated tool names. Three paused tasks:
  Aceptacion LCD/Sound en 001 (agentops__submit: add node=gway-001 before
  resuming); AgentOps Timer Health (status: specify 001 recommended);
  Activacion webOS TV (webos__read: specify 001 recommended).
  No automation modified or resumed.
- Provider doctor supports both shapes; 8/8 real snapshot comparisons.
- Before switching mode, inventory unindexed/private callers, local
  prompts, SDK/schema caches and other clients outside visible account.
  Explicit node mandatory for canonical execute; qualified aliases
  stay pinned. Refresh tool schemas after activation.

### Stage 1 activation (separate approval)
1. Require current main/PR base, green CI at exact HEAD, approved
   consumer migration and maintenance window. Capture sanitized catalog,
   scopes, release SHA, health and configuration metadata. Retain prior
   release and mode; no credential rotation/export.
2. Merge triggers automatic backend and Watchtower deployment. Use
   existing auto-deploy and watchtower-mcp.yml rollback path. Deploy code
   first in legacy default; verify both receipts, SHA, health and unchanged
   catalog/reads. Stop on failure.
3. Activate canonical-with-aliases separately through a persistent,
   operator-managed Ansible transaction for a dedicated gateway systemd
   drop-in (Environment=GWAY_MCP_NODE_ROUTING=canonical-with-aliases).
   This transaction is a rollout prerequisite, not implemented by this
   PR. Preserve other drop-ins, snapshot previous state, validate effective
   mode without secrets, restart only gateway. Verify no-op convergence.
4. Verify OAuth, canonical reads on 001/004, legacy reads, 004 alias,
   exact nodes/scopes and negative read admission; refresh MCP clients.
   Confirm no ABB routes and compare health with baseline.
5. On failure restore previous drop-in (or remove only the new one),
   reload/restart gateway; verify legacy catalog, aliases and reads.
   If code fails, use approved Ansible release-pointer/unit recovery and
   verify old SHA. Preserve credentials/enrollment/unrelated services.
   Do not remove aliases in stage 1.

### Stage 2 ABB-1 (separate approval, after stage 1 accepted)
ABB is enrolled/reachable but lacks a pinned transport and reports
execute_available=false. PinnedNode calls shell validate_command
(gway-NNN only); receiver hostname gate rejects ocpp-abb-1; and
CheckedNodeTransport requires execute_eligible even for provider reads.
Do not broaden these checks or grant general execution.
Design a distinct operator-pinned provider-read-only admission/transport
capability with existing enrollment/host-key binding, strict local node
identity, OCPP-only allowlist, provider_list/provider_read verbs only at
BOTH sender and receiver. Deny shell, provider_call, deploy and other
verbs on that channel; preserve existing GWay execution grants. Use a
fixed, approved provisioning recipe, not arbitrary remote execution.
First inspect installed CSMS revision and provider compatibility using
approved management access. Stage and persist the five read-only
provider tools from ocpp-csms #395 or a compatible reviewed successor,
with least-privilege stored-evidence access and no new charger traffic.
Keep CSMS running; separate approval if restart necessary. Record
preflight/backup and exact installed SHA, register the read-only pin,
then validate real canonical OCPP reads on both nodes, catalog/scope,
wrong-node and write denial, receiver policy, host-key mismatch,
revocation, offline behavior, idempotence and CSMS health.
Rollback removes only the new provider route and registration, restores
prior receiver/provider configuration if changed and verifies CSMS
continuity; keep enrollment and unrelated services intact.
Stage 3 removes qualified 004 aliases only after consumer migration and
ABB acceptance; canonical-only is separately approved and reversible.
