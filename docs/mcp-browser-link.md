# M2.1 browser bearer linking — Classic-style UX

When the ChatGPT private connector supports pre-registered OAuth authorization
code with PKCE S256, selecting **Connect** can redirect the browser to
`https://remote.arthexis.com/oauth/authorize`. That endpoint displays a
password-masked **GWA Remote bearer token** field, analogous to Classic GWAY.

The operator creates the original read-only bearer using
`sudo gway-remote bearer issue` **on the Watchtower console**, and pastes it into
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
- Console proof revocation or expiry invalidates its outstanding authorization
  codes and all derived access tokens, including after a gateway restart.
  Access-token lifetime cannot exceed its parent proof lifetime. The registry
  adds a delegation table when the administrator next issues a credential;
  existing console credentials remain valid.
- Pending sessions/codes are bounded to 1024 combined entries, expired entries
  are reclaimed before admission, and concurrent exchanges are serialized.
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

## Stable ChatGPT callback (RFC 9207)

For the ChatGPT connection whose UI displays
`https://chatgpt.com/connector_platform_oauth_redirect`, configure that **exact**
URL as `GWAY_MCP_OAUTH_REDIRECT_URI` in the protected Watchtower `link.env`.
Keep the pre-registered `GWAY_MCP_OAUTH_CLIENT_ID` aligned with the client
chosen in ChatGPT; our current server does **not** implement DCR or CIMD.

The built-in OAuth metadata advertises
`authorization_response_iss_parameter_supported: true` and canonical issuer
`https://remote.arthexis.com`. The browser flow includes that exact `iss`
on both successful authorization-code callbacks and redirectable OAuth errors.
Unknown client IDs, wrong redirect URIs and missing/invalid states fail locally
without redirecting. Do not enable Nginx OAuth/MCP public routes until the
operator has completed issue #305's real ChatGPT browser acceptance.


## Optional OAuth parameters and diagnostics

The HTTP endpoints follow RFC 6749 sections 3.1 and 3.2: ignore unrecognized
parameters, and treat empty parameters as omitted. Missing/empty authorization
scope defaults to the pre-registered client's only scope, `gway:read`. Explicit
scope escalation, duplicate parameters, mismatched client/callback/resource,
and invalid PKCE remain rejected. An empty `client_secret` compatibility field
is ignored. This is a public PKCE client (`token_endpoint_auth_methods_supported:
["none"]`); a nonempty client secret or Authorization header is rejected rather
than treated as verified client authentication.

The dedicated link service emits fixed-schema `oauth_link` diagnostic records
for discovery, authorization, browser proof and token exchange. They contain
only an allowlisted phase/reason, HTTP status and comparison booleans. No raw
request URL, parameter name/value, header, token, code, cookie, verifier, client
ID, callback, resource URL or exception text is recorded. Output is capped to
60 events plus one suppression notice per process per minute. Set
`GWAY_MCP_OAUTH_DIAGNOSTICS=0` in the protected link environment to disable it.

A reproduced optional-parameter failure is evidence of an interoperability
defect, not proof of why a particular ChatGPT attempt failed. Use the safe
phase/reason diagnostics from a new real attempt to establish that boundary.

Reference: https://www.rfc-editor.org/rfc/rfc6749.html#section-3.1

## Browser callback policy and repeated submissions

The authorization page allows form navigation to its own origin and the
configured HTTPS callback origin. Chromium can enforce `form-action` against
the redirect after the bearer form POST; `form-action 'self'` alone blocks
the return to ChatGPT even when the server accepted the bearer and sent 303.
The permitted external origin comes only from protected registered-client
configuration. Request parameters cannot add CSP origins, and the application
still requires the exact registered callback URI.

The form is one-time and expires after five minutes. A successful first click
consumes the session; submitting it again is `session_unavailable`, not proof
that its five-minute timer elapsed or the bearer was invalid. An expired or
unavailable form displays instructions to return to ChatGPT and start Connect
again. Keep the existing bearer; its validity is independent of the form timer.

Browser behavior reference:
https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/form-action

## Browser handoff after bearer proof

Some Chromium configurations block a cross-origin HTTP 303 at the end of a
form submission because of `Content-Security-Policy: form-action`. The bearer
proof is one-time, so pressing Connect a second time then returns 403 even
though the authorization code was minted successfully. The link service now
returns a same-origin HTML handoff page with a zero-delay meta refresh to the
exact configured OAuth callback and a **Continue to ChatGPT** link as fallback.
No JavaScript, new permissions, widened redirect allowlist, or additional
credential storage is required. If automatic navigation is blocked, click
**Continue to ChatGPT**, **not Connect again**. Restart authentication from
ChatGPT if the one-time authorization code expires.

Field validation: after deploying the reviewed release on Watchtower, retry
in a fresh ChatGPT Connect session and confirm the callback reaches ChatGPT,
that the token exchange succeeds and that a read-only tool can be called.
A passing HTTP-level regression test alone does not prove this browser flow.
