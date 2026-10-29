# M2.1 browser bearer linking — Classic-style UX

When the ChatGPT private connector supports pre-registered OAuth authorization
code with PKCE S256, selecting **Connect** can redirect the browser to
`https://remote.arthexis.com/oauth/authorize`. That endpoint displays a
password-masked **GWA Remote bearer token** field, analogous to Classic GWAY.

The operator creates the original read-only bearer using
`gway-remote bearer issue` **on the Watchtower console**, and pastes it into
the one-time HTTPS linking screen. No API or MCP scope can call issuance.

After verification and CSRF validation, the browser receives a one-time
authorization code, then ChatGPT exchanges it for a separate, one-hour,
read-only access token with S256 PKCE. No raw console bearer is saved in the
session, and the one-time code cannot be reused.

Files: `gway_remote/mcp_link.py`, `gway_remote/mcp_link_http.py`,
`deploy/mcp-bearer/gway-mcp-link.service`, and
`deploy/mcp-bearer/nginx-link-locations.example`.

**Important acceptance gates:**
- This is an initial *pre-registered client* OAuth flow. The real ChatGPT
  redirect URL and client identifier must be obtained and configured in
  protected `/etc/gway-mcp-gateway/link.env` as
  `GWAY_MCP_OAUTH_CLIENT_ID` and `GWAY_MCP_OAUTH_REDIRECT_URI`.
  Do not use test/example callbacks in production.
- Authorization codes/sessions are in process memory, so a restart aborts
  an in-flight login. The service runs as a single process.
- The current flow has no refresh-token grant, dynamic registration,
  external identity, or tested ChatGPT client support. One-hour access
  tokens may require reconnecting; refresh and issuer metadata acceptance
  should be tested before public activation.
- The token-entry screen is served by a **separate** loopback service
  running as the token administrator, not the read-only MCP gateway process.
  It never exposes broad command execution or bearer issue/revoke endpoints.
- The service unit and Nginx locations are **inert examples until explicitly
  staged and activated**; no public routes were modified by this PR.
- The existing Watchtower runtime audit found that the presumed
  `/usr/local/bin/python3` does not exist and `gway_remote` is not
  importable on Watchtower. An installed, isolated runtime is still
  required before any staging or activation.
