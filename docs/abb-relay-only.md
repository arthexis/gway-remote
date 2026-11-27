# ABB direct execution (#770)

Approved exception to #645: `ocpp-abb-1` only, existing `ubuntu` identity,
standard submit/result/cancel/limits. All other RPCs are denied at both ends.
The ubuntu account already has administrative sudo; this is administrative
execution, not a sandbox protecting production from arbitrary shell callers.
No AgentOps, Codex, managed deployment inventory or new credentials.

## Field acceptance after CI and release convergence

1. Use the existing strict Bastion route; compare live ABB ED25519 host public
   key with active Watchtower attestation. No keyscan or new enrollment. Check
   OCPP baseline, user bus and absence of conflicting relay artifacts.
2. Retrieve existing Watchtower relay public key from supported operator CLI
   for an eligible node; verify shared identity. Stage the approved clean Git
   commit on ABB, then run `ansible-playbook ansible/abb-relay.yml -i localhost, -e @REVIEWED_PUBLIC_VARS_FILE`.
   Supply only `gway_abb_relay_authorize: true` and `gway_exec_relay_public_key`.
   Never override hostname, identity, install root or journal. No private key
   movement. Check worker readiness, SSH policy and production health.
3. The journal `/var/lib/gway-abb-relay-provision.json` blocks partial retries.
   First-install rescue removes the new authorized key. A crash may leave
   partial files/accounts: keep central eligibility revoked; reconcile only
   positively identified new artifacts; preserve credentials and ledgers.
   Completed same-revision reruns verify without changes. A different release
   requires a separately reviewed package update.
4. After local relay checks, install the independently verified public host key
   at `/etc/gway-remote/verified-ocpp-abb-1-host.pub` on Watchtower. Use the
   existing grant CLI and `gway_remote.watchtower_pin_002` transaction with
   `--node ocpp-abb-1 --service-uid VERIFIED_UID`; apply with the distinct
   `I_ACCEPT_ABB_WATCHTOWER_PIN` approval and `--relay-confirmed` only after
   verification. See `watchtower-gway002-pin-transaction.md`. ABB journal:
   `/var/lib/gway-remote/watchtower-pin-abb`. On failure revoke ABB and recover
   with `--node ocpp-abb-1 --approval I_ACCEPT_ABB_PIN_ROLLBACK`. Preserve all
   existing nodes and reload only gateway if required.
5. Verify strict-pinned limits (1), direct MCP hostname/id, async result/cancel,
   duplicate binding, revoke and regrant, deployment preview/discovery denial,
   and unchanged OCPP services and other nodes. No charger traffic or restarts.


## Candidate read-only OCPP federation extension (#716, separate acceptance)

The original relay-only grant remains the baseline. The proposed protocol
extension admits only authenticated `provider_list` and
`provider_read` for the five fixed CSMS stored-evidence tools on
`ocpp-abb-1`. The receiver filters its root-owned manifest registry to the
exact CSMS immutable-release executable and schema-8 data directory already
owned by ubuntu. The manifest must not enable execute or contain a managed
deployment declaration. With no valid manifest, no ABB provider is exposed.
Both endpoints reject all other provider operations; node declarations cannot
add tools, and even an execute-scoped MCP principal uses the read RPC for ABB.
Canonical discovery introduces no new ABB aliases. Existing generic execution,
periodic health, pinning, keys, other nodes and deployment denials remain intact.

This candidate is **not a deployment authorization or upgrade procedure**.
The initial provisioning journal is revision-bound and must not be edited,
deleted or bypassed to install a new receiver. Before rollout:

1. Finish Stage 1's independent authorization and sanitized-rejection
   acceptance (#716, existing PR #732) without disturbing other release holds.
2. Review a separate receiver package upgrade and rollback transaction that
   preserves the original SSH key, attestation, fixed command, sudoers,
   service identities, active job ledger and original provisioning receipt.
   Gate on no active execution jobs, verify exact package and previous
   package, and retain the existing relay grant. Receiver first, gateway second;
   an old receiver still denies new RPCs. No new SSH keys or general deployment
   inventory. A gateway-only rollout cannot enable the old receiver.
3. Provision the CSMS read-only manifest through the repository-owned
   installer on the exact active CSMS release (`ocpp_csms_mcp_enabled=true`,
   `ocpp_csms_mcp_execute=false`) only within the approved CSMS maintenance
   gate. Do not handwrite an alternate provider registry or grant shell access.
   Verify the actual writer, provider revision, root-owned manifest and
   absence of execute. Do not restart a charging CSMS merely to register it.
4. Validate the five canonical tools against real stored evidence with
   independently authorized read and execute-scoped sessions; both must
   use only the read RPC for ABB. Verify missing/invalid manifest,
   wrong node, unknown tool, other provider, owner RPC, provider_call and
   managed deployment denial, with no charger traffic. Check other nodes'
   catalogs and periodic execution health. Keep #716 open until native
   and externally authenticated acceptance are independently attested.

No production authorization or rollout is implied by this document.
