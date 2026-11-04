# D1 — automatic Watchtower MCP deployment on validated main

## Topology

After the protected PR `CI` check passes and a change is merged to `main`, the existing `Deploy GWay Remote backend` GitHub workflow performs:

1. the existing automatic `gway-001` backend deployment;
2. a separate `Deploy Watchtower MCP` job using the **same** existing gway-001 self-hosted GitHub runner, even if the 001 deployment job fails.

The second job SSHes as the already configured `arthe` operator on 001 to the existing `gelectriic.com` SSH alias (Watchtower's `ubuntu` operator), using **BatchMode** and **StrictHostKeyChecking=yes**. No additional runner, SSH key, OAuth token or GitHub workflow secret is introduced.

On Watchtower, the approved `scripts/watchtower-auto-deploy.sh` wrapper runs from SSH stdin. It:

- accepts exactly one full lower-case hexadecimal commit SHA and checks it against the current `main` revision;
- requires an already provisioned/enabled Watchtower OAuth link and gateway, a non-root `ubuntu` operator, and already functioning unattended Ansible sudo;
- acquires the same `~/.local/state/gway-remote/deploy.lock` as manual `deploy.sh`;
- clones the fixed GitHub source into a **temporary, private, clean checkout** and verifies that its fetched HEAD equals the reviewed SHA. It **never modifies the operator's possibly dirty `~/Repos/gway-remote` checkout**;
- invokes only the existing `ansible/playbooks/watchtower-mcp.yml`, which stages the SHA, activates the isolated MCP runtime, checks gateway/OAuth health, and rolls back its pointer and units if activation fails;
- checks `/opt/gway-mcp/current`, the two existing service states, and local OAuth discovery before reporting success.

No reboot, new listener, credentials, reverse proxy, WireGuard or 001 service change occurs in the Watchtower job.

## Prerequisites (verified read-only on 2026-11-04)

- `gway-001` hosts the GitHub Actions runner under `arthe`.
- `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes gelectriic.com` from that user reaches Watchtower noninteractively as `ubuntu`.
- Watchtower has an enabled `gway-mcp-link.service`, an existing GWay checkout, `sudo -n true`, and access to `https://github.com/arthexis/gway-remote.git`.
- The Watchtower operator checkout was observed **dirty**; automatic deployment deliberately avoids writing there.

These observations establish transport prerequisites but **not** a production deployment receipt. Do not claim Watchtower auto-deploy accepted until its first merged-main workflow job completes and installed SHA matches.

## Idempotence, failure handling, and caveats

- A current SHA that is superseded before a job starts is skipped. If `main` changes while running, the fresh cloned revision must still equal the requested SHA; otherwise no deployment occurs.
- Rerunning the same SHA is safe: the existing Ansible playbook detects SHA and unit changes and restarts gateway/OAuth only as required. It still verifies identity and service health.
- A failure of the `gway-001` job does not prevent attempting Watchtower deployment. But if **the 001 runner itself is offline**, the Watchtower job cannot start; this intentionally reuses the existing trusted runner rather than provisioning a new one.
- Watchtower Ansible's `rescue` path restores the previous MCP runtime pointer and service units on a failed activation; a Git clone or SSH preflight failure changes no installed runtime.
- Existing manual `deploy.sh` on Watchtower remains supported and uses the same lock. No remote public ingress, token issuance or node execution permissions are modified.
- The runner's ability to SSH as the operator already exists. This job does not make it a general purpose deploy gateway; the workflow calls one pinned script and the remote script invokes one pinned playbook.

## Field acceptance

After PR CI and merge, inspect **the same main SHA** in the backend deployment workflow's two jobs:

1. `deploy`: verify the 001 install receipt and runtime health separately.
2. `watchtower`: verify noninteractive SSH, fixed SHA checkout, Ansible success, `watchtower_mcp_revision=<sha>`, and local OAuth discovery.
3. Confirm `/opt/gway-mcp/current` on Watchtower points to `releases/<sha>` and both `gway-mcp-link.service` and `gway-mcp-gateway.service` are active; ensure no unwanted changes to the separate OAuth proof registry, Nginx or WireGuard.
4. Run a subsequent no-op deployment of the identical SHA: Ansible should not restart healthy unchanged services; verify the final SHA again.
5. Fail/rollback acceptance can be validated with a hermetic Ansible fixture; do not intentionally break the live OAuth service.

This implements D1 only; MCP-triggered manual deployment to either host remains D2.
