# Node onboarding doctor — phase C of #549

This is a **read-only diagnostic**, not enrollment, attestation, deployment,
execution authorization or a node-health service. It introduces **no additional
registry, privileged role, token, SSH key, tool or endpoint**.

On the **Watchtower host**, using an existing identity authorized to read
the configured inventory and private transport evidence:

```sh
gway-remote node doctor gway-002 --json
gway-remote node doctor gway-001
```

The only automatic inputs are the existing short-lived root-published
`/var/lib/gway-mcp-auth/node-inventory.json`, operator-controlled
`/etc/gway-mcp/execute.json`, pinned `known_hosts` and SSH identity
**metadata**, and optionally checkpointed rows from the existing private
`/var/lib/gway-mcp-exec/requests.sqlite3` (strictly immutable/read-only).
The CLI never opens the private SSH key contents, launches SSH, performs MCP
`node_exec`, calls systemd, mutates SQLite, changes file permissions, creates
a credential, or modifies eligibility or atestation.

## Reading the evidence

| Status | What it can demonstrate | What it cannot |
| --- | --- | --- |
| Enrollment active | Node is in fresh authoritative Watchtower projection | Current reachability or deploy |
| Attestation verified | Active host identity was checked by the existing enrollment logic | Node executor health |
| Reachability reachable | Recently observed WireGuard peer reachability | Working SSH forced-command or service |
| Eligibility granted | Watchtower's existing, bound `execution_eligibility` grant | A remote job succeeded |
| SSH `pin_validated_offline` | Trusted local configuration, known_hosts fingerprint and identity-file metadata match the existing `PinnedNode` verifier | An actual SSH connection |
| Request ledger `readable_checkpoint_only` | Private SQLite can be read without writes; it may omit uncheckpointed WAL transactions | Current job availability |
| Terminal result `historical_succeeded` | Watchtower previously persisted success for this node bound to the selected host key | Current operational health |
| Recipe/executor/systemd bus `unknown` | No proof was gathered from the node | That these components are installed, broken or healthy |
| Installed release `unverified` | No SHA observation occurred | That the source manifest or deploy receipt proves active SHA |

The main distinction is **`ready_for_operator_test` versus
`operational.state=unverified`**. Even when registration, attestation,
reachability, grant and pin are all confirmed, this doctor does not claim a
working executor. Exit status **0** means conditions for a **separately
authorized test** are observed, *not* that the node is operational. Exit
status **1** means readiness is not established, **2** means invalid node ID
or malformed input.

A successful historical request must come from the existing private
Watchtower ledger, match the enrolled node and pinned host SHA, have
`state=succeeded`, and must not be a deployment request. No new request is
created to populate that ledger. Its checkpoint-only reading may miss newer
WAL rows; that absence is **unknown**, not a failure. Any unverifiable
input stays unknown. Command text, node addresses, key fingerprints, tokens
and private file paths are never included in the report.

## Operator continuation (separate, explicit authorization)

1. Complete enrollment and host-key attestation through the **existing**
   Watchtower operator workflow; check that the authoritative node snapshot is
   fresh. Do not derive eligibility from a handwritten inventory entry.
2. Review the explicit per-node **Ansible** recipe and existing forced-command
   transport configuration. Only install it on the node deliberately selected
   by the operator; do not treat the recipe as installed without evidence.
   Do **not** change gway-001's `arthe` executor selection.
3. Review the Watchtower execution grant and pinning. The node does **not**
   independently authorize or refuse execution based on a new opt-in; the
   Watchtower enrollment/attestation and central execution eligibility remain
   authoritative. No automatic privilege or credential changes.
4. Use the *already authorized* MCP `node_exec` and `node_result` tools
   in a separately approved field test to verify SSH forced command, correct
   effective identity, user bus, actual job completion and exact installed SHA.
   A preview alone is **never** proof. No field test occurs in this PR.
5. Keep the `node doctor` result `operational=unverified` until fresh,
   authenticated terminal evidence is independently observed. The root-owned
   manifest and historical receipt are not substitutes for an active SHA.

All tests for this PR run in disposable local fixtures and never enroll a
node, open a production SSH session, grant permissions or deploy services.
Do not merge or deploy the Draft without later authorization. Phase D is
separate.
