# GWay Remote OAuth refresh-token support

This extends the **existing** Watchtower OAuth authorization server and its existing `/oauth/token` route. No second MCP endpoint, separate login, Ansible identity change, or OAuth SDK/framework adoption.

## Behavior

- The initial PKCE `authorization_code` exchange returns an hour-long access token and an opaque `refresh_token`.
- A client can send `grant_type=refresh_token`, `client_id`, `resource=https://remote.arthexis.com/mcp`, and `refresh_token` as `application/x-www-form-urlencoded` to the **same** `/oauth/token` endpoint. The registered public client ID and resource must match.
- The server atomically consumes that refresh token and returns a **new access token and a new refresh token**. It never accepts a refresh credential as an MCP bearer access token.
- The refresh credential and all derived access tokens inherit the original operator proof's exact `gway:read` or `gway:execute` scope and absolute expiry. Refresh cannot upgrade read credentials or extend a proof's lifetime.
- The refresh grant's state persists in the owner-controlled Watchtower SQLite registry across service restarts. Only the token-admin OAuth-link service mutates it; the MCP gateway remains a read-only verifier.
- The OAuth refresh-token chain is bound to a hidden credential family; replay of a **previously consumed, correctly authenticated** refresh token revokes the family, invalidating all access and later refresh tokens in that family. A bogus token, wrong client ID or resource does not revoke other credentials.
- Revoking or expiring the original console bearer immediately invalidates all derived access and refresh credentials; operator authorization and existing node grants remain unchanged.
- Existing access tokens remain valid until their original expiry (or revocation). Existing pre-refresh OAuth connections cannot obtain a refresh token retroactively and will need **one** normal reconnection to receive the new credential pair.

## Security and compatibility

The gateway never receives refresh tokens and never gains write access to the token registry. Logs show only bounded categorical audit events, never token values or client parameters. The public PKCE client still has no client secret; only the already-registered client and resource are accepted. Unauthorized refresh fails as `invalid_grant`. Modern and legacy MCP transports, tool names, and OAuth scopes are unchanged.

The refresh token is confidential: store it in the MCP client's existing secure credential storage. One-hour access tokens are intentionally kept short; refresh tokens are valid only within the original operator bearer term (up to 90 days). A user may still need to reconnect after operator-proof expiry, revocation, client credential loss, or an invalidated refresh chain.

## Release acceptance

1. Merge only after full CI and HTTP integration tests pass, including rotation, scope binding, replay, parent revocation, expiry and legacy token compatibility.
2. Deploy to **Watchtower only** using the existing release mechanism; no `gway-001` service changes needed.
3. Confirm OAuth discovery advertises `refresh_token`, then reconnect the ChatGPT plugin **once** using the existing valid execute-scoped operator proof to obtain the refresh credential.
4. With controlled non-secret test tokens, validate a successful refresh after an access token ages out, plus rejection of reused/expired/revoked refresh tokens. Verify read-only and `node_exec` tools still operate with the same client connection.
5. Monitor whether ChatGPT actually uses token renewal. If it still prompts for reauthorization, collect sanitized OAuth token-request categories and client behavior; server-side refresh support alone cannot force a client to refresh.

Do not expose operator bearer secrets, access/refresh tokens or full request bodies in issue comments, CI logs or diagnostics.
