# Explicit gway-004 executor migration — Remote #615 / AgentOps #96

This is an **opt-in field cutover recipe**, not an automatic deployment, bootstrap
option, provider impersonation mechanism, or per-request identity selection.
Normal deploy.sh and the bootstrap URL still preserve an existing executor
identity, as required by #617. The new playbook is dormant unless invoked
**locally on the physical gway-004** with explicit approval and a reviewed SHA.

## Why this route

gway-004 runs its MCP forced-command receiver as gway-exec, but the immutable
AgentOps release and workspace are private to arthe. The existing node
provider adapter intentionally launches registered stdio providers only under
the receiver's effective UID. Changing a manifest's run_as or environment
cannot fix that without undermining the ownership boundary.

A per-provider cross-user handoff would introduce another IPC listener and
authorization/receipt boundary. Instead this recipe reuses the existing
identity, user-manager, protected ledger, SSH ForceCommand, exact sudoers,
byte-for-byte rescue and import checks from node-exec-select.yml. It does NOT
add a new daemon, socket, credential, SSH ingress, sudo rule, OAuth scope,
provider manifest, tool approval system, or service.

**Security cost:** existing execute-scoped node_exec can run arbitrary shell
commands (within its job size/time/memory limits). After switching to arthe,
the operator's existing home access and effective privileges, potentially
including sudo and SSH-agent access, become reachable to trusted callers with
gway:execute for gway-004. This is broader than AgentOps-only delegation.
The user must independently approve this trust boundary after confirming the
local passwordless sudo policy, SSH agent exposure, and execute principals.

## Field preconditions (separate approval, no activation in this PR)

1. Approve the broader gway-004 execute-scoped Unix privilege boundary. Verify
   that arthe's own credentials remain private; never copy tokens from 001.
   Verify no unexpected passwordless sudo grants or usable privileged agent
   sockets and that Watchtower's gway:execute callers are trusted.
2. Establish a *real ingress-quiesced window* for gway-004 (both shell and
   provider submissions). The read-only preflight sees current ledgers but
   **cannot guarantee** that an incoming job will not race with SSH reload.
   An external operator must demonstrate that no admissions can start until
   the cutover is accepted. Do not treat the existing maintenance-lock Draft
   PR #590 or CI as proof of this guarantee.
3. Have an independent pre-established pinned operator route to gway-004, a
   real rollback operator, the current node's SSH/visudo permissions and an
   exact checked-out reviewed merge SHA. Do not use SSH TOFU/keyscan. Verify
   that the **installed /opt/gway-remote receiver** already contains the
   generic post-#617 executor runtime (not merely that the checkout does).
   Do not run the migration against the old e78bc989 receiver.
4. Freeze or reconcile old jobs: no queued, running, unknown, uncertain or
   malformed states in the gway-exec SQLite ledger. Keep existing receipts
   and ledger ownership untouched. Read the old ledger only; no force unlock,
   copying history, or retry of an uncertain request.
5. Verify arthe's systemd user bus exists, root-controlled existing executor
   policy and exact gway-relay ForceCommand/sudoers agree, and rollback access
   remains reachable throughout.

If any gate cannot be met, **do not run** the migration. Source CI alone is
never a substitute for admission quiescence or field acceptance.

## Exact operator-only invocation (after explicit field approval)

From a clean, reviewed checkout **on gway-004 itself**:

    ansible-playbook -i 'gway-004,' -c local ansible/migrate-executor-004.yml \
      -e gway_executor_migration_approval=I_ACCEPT_GWAY_004_EXECUTOR_ARTHE \
      -e gway_executor_migration_expected_sha=<FULL_REVIEWED_MERGE_SHA>

The playbook asserts both the Ansible target and actual hostname are gway-004,
requires a clean tracked/untracked source tree and exact 40-hex HEAD, and runs
the read-only preflight from the installed package identity contract. The
preflight refuses root mismatch, unexpected old identity, missing/unsafe
ledger, any nonterminal/unknown state, a missing post-#617 executor_path
capability, and inconsistent fixed SSH/sudoers policy. It emits only a short
nonsecret receipt. The playbook then calls the **existing** node-exec-select
tasks, which check the arthe user bus, old jobs, private state, root policy,
SSH/visudo agreement, and restore original bytes if the guarded block fails.
The existing file_read sudoers exception remains gway-001-only.

A second identical invocation may be idempotent after the selected identity
and relay agree. The old gway-exec ledger is preserved, but **node_result
under arthe cannot be assumed to retrieve older gway-exec receipts**. There
is no hidden automatic history migration. Preserve the independent evidence.

## Acceptance after an independently authorized activation

Read-only checks first: installed package SHA/capabilities, selected user,
root policy, SSH/sudoers, gway-004 node_exec id -un (expect arthe), then
provider_list/ provider_read on AgentOps, Watchtower discovery of
gway_004_agentops__* distinct from gway-001, and no read-to-write or
wrong-node bypass. One bounded real AgentOps execution and local authentication
acceptance belong to AgentOps #96, not this code PR; the 004 scheduler remains
disabled. If the switch or follow-up validation fails, use the existing
guarded rescue/rollback after re-establishing safe admission quiescence and
checking both ledgers; never edit old receipts to make a rollback pass.

No gway-002/005, OCPP server, Watchtower deployment policy, WireGuard, DNS,
PAM or network changes are in this increment. #615 and AgentOps #96 stay open
until independent field evidence and acceptance.
