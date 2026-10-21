# Watchtower M1b — existing enrollment contract inspection

Read-only field instructions for [issue #199](https://github.com/arthexis/gway-remote/issues/199).

**Confirmed:** `register.gelectriic.com` is the Watchtower host, Nginx owns an exact `/v1/enroll` route, and `gway-wire-enroll.service` is active. **Do not deploy a parallel service.**

## Field inventory (do not change runtime)

1. Determine the exact systemd ExecStart executable, release identity and source package/module behind `gway-wire-enroll.service`; report package names and source repository if identifiable. Check relevant HTTP route definitions by inspecting **code**, not issuing POST requests.
2. Document the request and response schema of `/v1/enroll`, accepted HTTP method, expected status codes, authentication, allowed client IPs, single-use handling, replay protections and network failure handling.
3. Identify whether the handler itself writes `/etc/wireguard/gway.conf`, calls `wg set`, invokes a privileged helper or delegates to a different service. Report any locks, backup, rollback, atomic replace and idempotency behavior. Never print keys or full configuration.
4. Find authoritative address pool and reservation persistence (if any); report storage path, schema/table names and aggregate counts only. Verify compatibility with the existing peer and the offline `gway_remote.wireguard_invitations.InvitationStore` contract; do not copy private DB data.
5. Inspect sanitized Nginx logging directives for `/v1/enroll` and evaluate how to avoid ever including invitation credentials in URL paths, query strings, headers or logs. Identify whether a public immutable bootstrap payload can be served separately.
6. Identify a viable **private authenticated** management interface for Watchtower's CLI, preferably Unix socket/SSH or existing private WireGuard access. Document exact operational ownership and permissions, not credentials.
7. Inspect provider security group externally via an authorized AWS operator if access is available; otherwise report an explicit blocker.
8. Recommend **extend vs replace**, including minimal implementation seams, migration safeguards, unit/Ansible ownership and a test plan. Do not install or restart any service.

## Deliverable

One redacted issue comment containing a module/route ownership map, a `/v1/enroll` request/response contract, allocation and persistence findings, the authorization/logging matrix, and go/no-go gates for extending the existing service.

This inspection remains strictly read-only; it must never trigger a registration, invitation, WireGuard mutation, service restart or firewall change. Do not use Agent Ops.
