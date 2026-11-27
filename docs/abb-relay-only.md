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
