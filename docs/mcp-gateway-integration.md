# ChatGPT MCP gateway integration gate

Public address: `https://remote.arthexis.com/mcp`, TLS termination on
`gelectriic.com`. Gway-001 hosts the read-only MCP application. These
identifiers name different roles; they are not interchangeable.

## Current status

The merged M2 application is **not an OAuth authorization server**. It
requires `GWAY_MCP_BEARER_TOKEN` and only accepts loopback connections.
This repository does **not** provision an OAuth provider, a gateway-to-Gway-001
private transport, a public Nginx location, or a ChatGPT plugin on its own.
Merely configuring Nginx to inject a static bearer token is not sufficient
operator authentication: without upstream per-user authorization, anyone with
network reachability could acquire Agent Ops issue metadata.

## Before enabling public ingress

1. Select and configure a trusted OAuth 2.1 authorization server (or use
   ChatGPT Secure MCP Tunnel for a strictly private plugin). Confirm provider,
   client registration, protected-resource metadata, user/operator allowlist,
   token audience and scopes, token expiry and revocation. Never store secrets
   in Git, workflow logs, public URLs or ChatGPT messages.
2. Implement a gateway validator that checks each request's bearer token and
   operator authorization **before** forwarding to the backend. Reject all
   anonymous or insufficiently scoped requests; pass only `/mcp` (no mobile
   API routes, arbitrary proxying, issue mutation or Codex access).
3. Bridge the gateway to the local MCP listener through a separately reviewed
   private connection. Since the application is bound to Gway-001
   `127.0.0.1:8770`, Nginx on the remote server cannot reach it by proxying
   its *own* localhost. Preserve listener binding and independent backend
   authentication. Restrict the tunnel endpoints and verify host identities.
4. Validate DNS, certificate, SNI, Nginx vhost and route independently.
   Stage and lint configurations, review access/rate limits, then authorize
   activation separately. Avoid changes to existing mobile API ingress.
5. For a controlled smoke test, inject a short-lived authorized test token via
   a local environment manager, then run:
   `GWAY_MCP_SMOKE_URL=https://remote.arthexis.com/mcp python3 scripts/mcp-smoke.py`
   (the token must already be set in `GWAY_MCP_SMOKE_TOKEN`).
   It checks negative authentication, MCP initialization and **exactly four**
   read-only tools. It does not invoke Agent Ops or `agent_submit`.
   A successful smoke test is not proof of ChatGPT plugin connectivity.
6. In ChatGPT Plugins select Add custom MCP server and supply the verified
   URL and supported authentication flow. Verify actual `tools/list` and a
   representative *read-only* tool call from ChatGPT. If blocked, report the
   precise capability/permission failure without copying credentials.

See current OpenAI guidance:
- https://developers.openai.com/api/docs/guides/custom-mcp-server
- https://developers.openai.com/plugins/build/auth
- https://developers.openai.com/api/docs/guides/secure-mcp-tunnels

M3 `agent_submit` is not part of this increment.
