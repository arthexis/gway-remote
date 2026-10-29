# M2.1 Watchtower readiness and staged authentik deployment

## Gate A: Read-only host audit
Run on the **actual Watchtower** (not gway-001) using SSH via the existing bastion identity:
```sh
sh scripts/watchtower-auth-readiness.sh
```
Record only sanitized facts. This repository has **not executed this command on Watchtower**.
Requires >=2 CPU cores and >=2 GiB RAM per authentik's documented Compose minimum; check available
RAM headroom, root/data volumes, running workloads, Docker Engine + Compose v2, port conflicts,
existing Nginx/TLS ownership, DNS for `auth.gelectriic.com`, backup storage, and rollback.
**Do not install** when resources are inadequate or an established reverse proxy owns the port.

## Gate B: Review-only pinned deployment
`deploy/authentik/compose.yaml` describes a **dedicated, opt-in** authentik stack:
- authentik server + worker tagged `2026.8.5` (verified upstream release 2026-10-21);
- PostgreSQL image version tag pinned to `16.10` (verify upstream registry tag before deploy);
- only `127.0.0.1:19000` bound on the host; no HTTP/HTTPS public listener;
- Docker socket deliberately not mounted;
- protected secrets via a private `.env`, no committed production credentials;
- named persistent volumes for DB, media, templates and certs.

**This is version-tag pinning, not immutable digest pinning.** Before production, resolve
multi-arch digest(s), review deployment architecture and replace tags with immutable
sha256 image references in a follow-on commit. Confirm postgres version compatibility,
image signatures and release advisory.

Before any launch: choose backup target and test PostgreSQL restoration; establish
MFA and operator allowlist; plan identity provider availability and documented secret
rotation. A production `.env` must be owner-only (0600), not tracked by Git.
No automation in this PR runs `docker compose up`, changes firewall, creates TLS,
adds DNS or modifies public routing.

## Activation after independent approval
1. Run the audit on Watchtower and review resources/port conflicts.
2. Approve pinned image digests and stage deployment on private loopback.
3. Validate health, database persistence and restore, then configure administrator MFA.
4. Configure GWA OAuth application/provider with a pre-registered ChatGPT OAuth client;
   verify exact redirect, issuer, `resource`, `gway:read` authorization and PKCE S256.
5. Only after gateway JWT validation is tested, separately authorize public TLS routing
   for `auth.gelectriic.com`; **do not** enable `remote.arthexis.com/mcp` in M2.1.

## Non-goals
No public MCP listener, no `gway:submit`, no mobile API changes, no Agent Ops execution,
no provider startup or credential generation in CI.

Sources: https://docs.goauthentik.io/install-config/install/docker-compose/
and https://github.com/goauthentik/authentik/releases/tag/version%2F2026.8.5
