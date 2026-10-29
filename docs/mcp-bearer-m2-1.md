# M2.1 — Console-issued bearer, read-only

Status: under review. No service or public route is activated.

Watchtower operator issues the gway:read credential locally:

    python3 scripts/mcp-bearer.py issue --days 30
    python3 scripts/mcp-bearer.py revoke KEY_ID

Store the plaintext secret securely; it is printed once, never stored in the SQLite registry.
The registry uses a 0700 directory, 0600 database, random credentials, hashed verifiers, expiry and revocation.

## Integration remaining

1. Add a separately authenticated HTTPS gateway verifying the bearer through BearerRegistry.verify() per request.
2. Allowlist only /mcp, JSON-RPC read operations, bounded requests and the seven existing read-only tools.
3. Forward exclusively to gway-001 through WireGuard after authorization; replace user bearer with independent backend credential.
4. Verify ChatGPT private plugin connection supports API-key headerScheme=bearer. Plugin manifest supports it, but submission portal does not; use Classic lightweight OAuth as fallback if necessary.
5. Negative tests: expired, revoked, wrong-scope, missing credentials, malformed paths/tools, untrusted origins, log redaction.

M2 issues gway:read only. gway:submit remains M3 and requires explicit approval. Do not activate a public route merely because CI passes.

Docs: https://developers.openai.com/plugins/build/plugins