# MCP authentication and bearer provisioning

This document describes the existing operator authentication workflow for GWay Remote. It is not a deployment or enrollment runbook. Follow the currently installed CLI and runtime declarations for supported commands, scopes, and operational behavior.

## Existing authorization model

- The public OAuth/MCP boundary distinguishes `gway:read` and `gway:execute`. Read-only access must not dispatch execute operations.
- An authorized operator's execute-scoped connection can use read and execute tools without a second bearer or per-command approval. Scope enforcement, node eligibility, pinned identity, and existing execution safeguards remain in effect.
- No separate authentication step, approval workflow, new service account, or new MCP tool is introduced by these instructions.
- Do not interpret credential issuance as permission to enable nodes, change SSH trust, or deploy services.

## Issuing and protecting an operator bearer

Use the existing canonical CLI from an appropriately authorized Watchtower session:

```sh
sudo gway-remote bearer issue --scope gway:execute --days 90
```

For a deliberately read-only client, use `--scope gway:read` instead. Choose the scope and lifetime appropriate for the client; the example is not a requirement to issue or rotate a token for an already-authorized connection.

The current issuance CLI requires TTY input and output. Authorized automation or an operator may use a **protected pseudoterminal** to transfer the one-time credential directly into an owner-only secret destination. This is an implementation detail of the *existing* issuance path, not an extra approval or credential mechanism.

Never place bearer plaintext in shell logs, CI logs, issues, chat or agent transcripts, URLs, or repository files. Do not display a credential merely to prove a deployment. Keep existing credentials until their normal expiration or revocation; no new token is needed per command.

Revoke a bearer using its public key identifier, **not** its secret:

```sh
sudo gway-remote bearer revoke <key-id>
```

## OAuth connection behavior

Use the existing OAuth browser-link flow and the operator bearer of the appropriate scope. An execute-scoped operator connection covers ordinary read and execute operations; do not create a redundant read-only connection solely for discovery. A deliberately read-only connection must remain read-only and must not be silently elevated.

Refreshing tool discovery is not credential issuance or a permission change. Reconnection, where required by the existing OAuth access-token lifetime, reuses a still-valid operator bearer; it does not create a new per-command approval.

## Acceptance boundary

OAuth and scope isolation are centralized gateway contracts. Revalidate live
independent OAuth authorization when that boundary changes (including token
validation, scope classification/enforcement or authorization transport).
Ordinary feature changes inherit the existing authorization contract and must
pass applicable gateway and provider scope regression tests, authenticated
functional acceptance and receipt reconciliation when relevant. Do not require
new credentials, manual token export or a separate live OAuth acceptance client
for each feature merely because it consumes the shared authorization path.
This policy does not relax scope enforcement or release/publication gates.

## Historical implementation material

The retired `docs/m3-b2b3-activation.md` described an M3 milestone, early gway-001-specific relay setup, and field acceptance steps. Its original contents remain in Git history and **must not** be treated as current deployment instructions. For node enrollment, relay configuration, identity and deploy operations, consult the relevant current implementation and dedicated operational guidance rather than reviving milestone-specific steps.
