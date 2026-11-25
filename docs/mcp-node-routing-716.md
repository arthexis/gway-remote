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
