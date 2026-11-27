# Native Watchtower execution health (#776)

Every five minutes the local systemd timer invokes the fixed
`periodic_execution_health` entry point under the existing private gateway UID.
No MCP tool, bearer scope, arbitrary command argument, scheduler provider or new
SSH key is introduced. The existing gateway UID and root are trusted (the unit
is not a privilege separation boundary against malicious code running as that
UID). The two relay operations accept only a node and slot-derived request ID;
the receiver chooses `/bin/hostname`. A verified result requires exact hostname,
exit zero, no diagnostic/truncation and matching request/pin.

- Current enrollment, reachability, grant and pin are checked before each
  operation. Revoked nodes are skipped. Under the receiver's existing SQLite
  admission transaction, any queued/running job blocks a new probe, even with
  spare capacity. No ordinary job is cancelled or reconciled by the monitor.
- A deterministic per-node five-minute ID and durable claim precede dispatch.
  Same-slot restarts reconcile result only; never replay submit. Expired
  submissions and clock regression are denied. Separate receipt tables retain
  seven days centrally and six prior slots locally. Only expired monitor-owned
  terminal records are retired; ordinary histories and tombstones are untouched.
- Read-only inventory merges qualifying manual and periodic receipts. Fresh
  success = verified, confirmed failure/timeout = degraded, absent/stale/uncertain
  = unverified. Busy preserves still-fresh evidence. Timestamps reflect initial
  claim, not reconciliation time. No output or IDs are exposed.

## Staged rollout

1. Merge with CI and verify exact backend/Watchtower revision.
2. Stage reviewed clean commit locally on each pinned receiver via existing
   strict administrative route. Run `ansible-playbook ansible/playbooks/periodic-health-receiver.yml -i localhost, -e gway_periodic_health_authorize=true -e gway_periodic_health_node=NODE`.
   Updates only existing content-addressed Python receiver package, checks host,
   relay and idle ledger, reports prior pointer. Preserve ABB provisioning receipt.
3. On Watchtower run `ansible-playbook ansible/playbooks/watchtower-periodic-execution-health.yml -i localhost, -e gway_periodic_health_authorize=true`.
   Units are staged but timer is not enabled. Start the service once; inspect
   sanitized journal and node_list, verify all eligible receivers and production.
4. Repeat with `-e gway_periodic_health_enable=true` only after acceptance.
   Verify next tick. Disable/stop the timer before any receiver rollback; retain
   receipts and original reviewed package pointers. A gateway rollback lacking
   the new entry point fails closed. No credentials or job data are removed.
