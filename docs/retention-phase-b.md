# Issue 306 — Agent Ops canonical deployment boundary

Agent Ops is not a special installation owner. Its canonical `deploy.sh` is in
`arthexis/gway-agent-ops` (coordinated PR #54). GWAY Remote's
`deploy_agent_ops` clones and verifies the approved commit, calls the owner
wrapper, and independently verifies the installed executable SHA and CLI probes.

## Contract

- Install root: `~/.local/share/gway-agent-ops` for the non-root appliance account
- Immutable release: `releases/<40-hex-sha>`
- Activation: `~/.local/bin/agent`; `current` and `previous` owner-managed
- Lock: `<root>/.deploy.lock` held across installation, activation, verification and metadata
- Verification ledger: `<root>/verified-releases.json` (successful installation only)
- Failed installed CLI verification restores the prior `agent` link under lock
- No Codex execution, credential adoption, service restart or data migration
- No pruning/deletion, automatic or manual, in this increment
- Legacy Agent Ops releases remain present and non-deletable

Owner source `deploy.sh` is the single installation path. Remote does not write
owner release directories, owner retention history or activation links. The
existing read-only `gway-remote retention` preview remains available with
`deletion_enabled: false`.

## Merge/deploy sequence

1. Merge Agent Ops PR #54 first; do not deploy a revision that lacks `deploy.sh`.
2. Merge Remote PR #308. Remote will reject installation of older Agent Ops
   commits that lack an owner installer rather than fall back to its removed
   in-Remote implementation.
3. When validating the next *approved* Agent Ops deployment, verify only the
   installed SHA, `agent --help` and `agent --version`. Do not repeat the
   complete retention test suite or perform a cleanup test for this increment.

## Phase B still open

Owner runtime/process and systemd reference completeness, indirect consumers,
shared dependency references, rollback policy, snapshot/verification safety,
prune revalidation and receipts still require implementation and acceptance.
The approved read-only preview must not mark releases deletable until these
conditions are met. Remaining owners have their own canonical installers;
none should delegate release ownership back into Remote.
