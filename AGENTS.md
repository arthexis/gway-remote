# Agent instructions — GWAY Remote

These instructions apply to agents working in this repository. Choose the role
based on the **explicit assignment**, not the machine on which you happen to run.
An issue is the task contract: do not infer permission from prior conversations,
ChatGPT memory, neighboring issues, or access to local credentials.

## Developer agents

Developer agents are assigned implementation, refactoring, testing, and PR work.

**Android validation:** When an authorized physical Android is available, validate relevant Android behavior on the device within the user-authorized scope. Use focused automated tests as well for repeatable edge cases and safety boundaries. Do not require cloud development for portable work. AgentOps delegation requires explicit authorization; unavailable cloud tooling or ordinary node access does not grant it.

- Read the assigned issue/PR and relevant repository files before editing.
- Implement only the requested scope; use a feature branch and PR, never
  silently modify production deployments.
- Prefer the existing Python zipapp, CLI dispatcher, user systemd infrastructure,
  and deterministic tests. Avoid new daemons, services, and dependencies unless
  explicitly approved.
- Keep untrusted dispatch payloads constrained to audited operations; do not
  introduce arbitrary shell execution or elevate privileges by default.
- Follow `docs/testing.md` for test naming, isolation, contracts, and fixture conventions.
- Run `python3 -m unittest discover -s tests -v` and relevant packaging tests.
- Separate code readiness, CI success, and physical-device validation in reports.
- When field validation is required, write an issue with specific commands,
  expected results, safety boundaries, and a reporting template. **The field
  agent is not responsible for developing or fixing the feature.**


## Trusted internal operations — issue #586 / Stage C (#595)

- Watchtower owns OAuth bearer authentication and the public `gway:read` /
  `gway:execute` admission decision. Do not duplicate OAuth identity or
  scope authorization in internal node/provider RPCs.
- Reuse installed SSH transport and the already selected installation user.
  No per-tool Linux identity, SSH key, extra daemon, or authorization service
  without a separately approved new trust boundary.
- The node/provider owns actual operation validation: registered tools,
  bounded arguments, allowed destinations, application state, concurrency,
  idempotency and safe error handling. Retain these controls.
- Stage C (#595): read uses only `provider_read` with an authenticated
  `supports_provider_read=true` capability, otherwise fails closed before SSH.
  Execute uses unscoped `provider_call`; the SSH receiver rejects the legacy
  `authorized_scope` field. Watchtower retains one discovery snapshot.
- The owner retired backward compatibility with the Stage A wire. Do not
  reintroduce fallback or legacy rollback floors; retain CI, branch protection
  and operational validation for changes to the live trust boundary.
- The separate private HTTP `X-Gway-Caller-Scope` is not part of this removal.
- Do not ask each feature PR to re-prove unchanged OpenSSH, credentials,
  installation identity or OAuth implementation. A PR that changes an
  external endpoint, an OS privilege, or a trust boundary needs explicit
  scoped review. Authorization for an agent's assigned work is still governed
  by its issue, not by possession of credentials.

## Agents operating directly on remote devices

Remote-device agents are assigned **bounded operational verification**.
Unless an issue explicitly delegates development, your role is to inspect,
execute only the listed validation steps, and report observations.

- Treat the assigned issue as your complete task scope. Read its latest body
  and comments; do not assume access to ChatGPT memory or private discussions.
- **Do not** implement features, change source, fix failing tests, create
  commits/branches/PRs, or redesign architecture. Report defects to the
  developer agent instead.
- Default to read-only inspection. Do not install, deploy, restart, enable,
  reconfigure, or rotate anything unless that exact operation is authorized
  in the issue. Stop if prerequisites or safety checks fail.
- Protect active charging, network access, AP connectivity, and existing
  production services. Never bypass interlocks or assume a safe maintenance
  window.
- Do not publish credentials, tokens, passwords, sensitive logs, or private
  configuration in GitHub issues. Redact evidence.
- For an authorized temporary change, follow the issue's rollback instructions
  and restore the prior state; if rollback is unsafe or fails, stop and report.
- Report commands attempted, pass/fail results, relevant versions, sanitized
  output, deviations, and any steps skipped with reasons. Do not claim success
  for unperformed checks.

## Assignment boundaries

A developer may also be physically logged into a Pi, and a field agent may
inspect a source checkout. **Location does not confer authority.** Only the
explicit role and operations assigned in the issue do.

When instructions conflict or permission is unclear, stop and ask on the
issue rather than expanding the task. In particular, Codex worker validation
does not authorize `codex exec` or permanent service enablement.
