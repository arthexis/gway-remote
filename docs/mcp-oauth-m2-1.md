# M2.1 — Self-hosted OAuth identity preflight (not activated)

Parent: [#233](https://github.com/arthexis/gway-remote/issues/233).
This increment is **staging and verification**, not public MCP activation.

## Selected architecture

- ChatGPT: OAuth authorization-code + PKCE S256 client.
- `auth.gelectriic.com`: self-hosted authentik, operated on Watchtower, with
  TLS, persistent database, backups, administrator MFA and security updates.
- `remote.arthexis.com/mcp`: MCP protected resource and token-verifying gateway.
- `gway-001`: existing private loopback MCP on `127.0.0.1:8770/mcp`.
- WireGuard and a separately authenticated private forward connect the gateway
  to the local MCP service. Never expose mobile API or MCP port to the Internet.

## Registration compatibility: gate before deployment

authentik 2026.8+ provides DCR but requires an authorized bearer token to
register new clients. **Do not expose anonymous registration or assume ChatGPT
can supply authentik's registration token.** First attempt a **preconfigured
OAuth client** with the exact redirect URI shown by ChatGPT's connection UI;
verify the provider supports the required client authentication and PKCE flow.
CIMD is an optional future option only after confirming provider compatibility.

Before declaring supported:
1. Confirm authentik discovery advertises authorization code, PKCE S256,
   compatible token endpoint authentication and stable issuer.
2. Verify the actual OpenAI client's redirect URI, client registration mode,
   refresh-token behavior, and `resource` propagation into access tokens.
3. Authenticate as an **allowlisted operator** using MFA and obtain a
   resource-specific access token. Enforce exact issuer, audience, expiry,
   signature/JWKS and `gway:read` at the gateway; reject anyone else.
4. Keep `gway:submit` reserved and **not granted** in M2.1.
5. Ensure all seven tools remain read-only, including GitHub Actions metadata;
   deny arbitrary commands, deploys, and `agent_submit`.

## Metadata contracts

Resource metadata (only after reviewed gateway configuration):

```json
{
  "resource": "https://remote.arthexis.com/mcp",
  "authorization_servers": ["https://auth.gelectriic.com/application/o/gwa-remote/"],
  "scopes_supported": ["gway:read"]
}
```

The authorization server's actual issuer must match **exactly**; verify path
and trailing slash against the deployed authentik discovery document.
Do not advertise endpoint availability until properly secured.

Run the *non-mutating* metadata checker only after the metadata endpoints
exist; pass the provider's actual documented discovery URL (no credentials):

```sh
python3 scripts/mcp-oauth-preflight.py \
  https://auth.gelectriic.com/application/o/gwa-remote/.well-known/openid-configuration
```

Discovery success does **not** mean a production gateway is authorized.
The operational rollout requires a separate approval, HTTPS/authenticator
configuration, token validation implementation, protected secret provisioning,
private WireGuard upstream, and read-only ChatGPT smoke test.

## Field checklist (no secrets in evidence)

- Record authentik release and supported runtime requirements; check Watchtower
  free RAM/storage and existing TLS/vhost conflicts before installing.
- Install from reviewed pinned artifacts with dedicated persistent volumes;
  use non-default generated secrets stored outside Git; configure database
  backups and restoration, rotation, MFA and a restricted operator group.
- Avoid publishing an OAuth route until the provider is healthy and
  authorization has been verified. Restrict admin endpoints separately.
- Verify token scope **and** audience with negative tests (wrong user, issuer,
  audience, expiry, signature, missing scope); require fail-closed behavior.
- Confirm ChatGPT can actually authorize and list/call seven read-only MCP
  tools; a local mock or HTTP 200 is not sufficient.
- Never reuse the mobile API bearer token as an OAuth resource token, gateway
  credential or provider signing secret.

**Status:** Implementation staging only. Provider, token-validation gateway,
public route and ChatGPT OAuth acceptance remain pending.

References:
- https://developers.openai.com/plugins/build/auth
- https://docs.goauthentik.io/add-secure-apps/providers/oauth2/dynamic-client-registration/
