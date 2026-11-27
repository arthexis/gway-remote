# Native Watchtower AgentOps coordination (#126)

The protected GitHub ref alternative is abandoned: private branch protection
requires a paid GitHub plan and existing node credentials have different
repository access. Watchtower is the only durable reservation authority.

## Protocol
Nodes persist private intents before any systemd launch or direct/audit
acceptance. Watchtower polls them with the existing pinned, enrollment-checked
SSH forced-command transport. Two internal verbs, agentops_coordination_snapshot
and agentops_coordination_apply, are available only on the trusted relay; they
are not MCP tools, HTTP routes or general execution grants. Only the exact
registered immutable AgentOps release is invoked with the fixed
coordination-exchange subcommand. Payloads contain an epoch and bounded
repo/identity hashes, reservation token and state. The transport derives
node identity; a request cannot select a path, executable or shell.

The dedicated SQLite ledger uses BEGIN IMMEDIATE and a unique partial index
for reserved repository keys, retains identities forever within a bounded
100000-row capacity (fail closed at capacity), and commits grants before
responding. Exact owner, token, repo and identity must match for release.
No lease expiry, automatic release after downtime, or reset. A lost
acknowledgement is reconciled with the same local durable intent. A finished
worker records a terminal intent only after durable local evidence; central
release occurs on the next authenticated poll. Unknown worker outcomes keep
the fence. Historical hashes must be seeded before real admission.

## Rollout (disabled by default)
1. Confirm exact reviewed revisions and CI. Enumerate every AgentOps-capable
   node, quiesce its existing workers/schedules and verify no older active
   receiver, provider, worker or scheduler can bypass the gate.
2. Install exact new node receiver and AgentOps release on each enrolled
   member via reviewed deployment recipes. Do not alter credentials, WireGuard,
   OAuth or Android. Confirm manifests and node identity.
3. Run isolated synthetic acceptance before activation. On each node, use
   a root-owned /etc/gway-agent-ops/coordination-canary.json
   with schema 1, same 32-hex epoch, members list, general_pickup_accepted
   false. Its separate owner-private coordination-canary mailbox cannot be
   used by a real worker. Test with an isolated Watchtower Ledger path
   under the existing gateway-owned private state directory (never the
   operational DB), same epoch and pinned transport. Compare two conflicting
   new synthetic intents, exactly one reservation, no duplicate, foreign
   release denial, exact terminal release and replay denial. No Codex launch.
4. Reconcile all existing dispatch journals at cutover (the reviewed private
   92-hash snapshot is a baseline, not a fresh quiescence proof). Root-owned
   /etc/gway-mcp/agentops-coordination.json has schema 1, epoch and members;
   root-owned /etc/gway-mcp/agentops-coordination-seed.json has those same
   fields plus history (normalized unique SHA-256 identities). Initialize
   once as the existing gway-mcp-gateway service identity using the immutable
   runtime launcher agentops_coordination --initialize. Existing DB is never
   overwritten. Back up and retain the epoch and history.
5. Stage disabled private timer with watchtower-agentops-coordination.yml,
   then test one tick under its existing gateway account. No public service.
   Install matching root-managed /etc/gway-agent-ops/coordination.json node configuration only on all reviewed
   members while quiesced, with general_pickup_accepted=false. Enable the
   private timer only after controlled acceptance; verify real periodic
   progression. No general pickup activation in this change.

Node config absence is legacy/manual compatibility prior to cutover, not
distributed exclusion. Do not claim global protection while any member is
legacy or the authority is uninitialized. Existing configured nodes refuse
admission if the mailbox config is removed; existing granted work remains
fenced by the persistent central ledger. Never restore an older coordinator
snapshot or reuse epochs after data loss without reconciling every node.
