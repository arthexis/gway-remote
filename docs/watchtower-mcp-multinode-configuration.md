# Watchtower MCP multi-node execution configuration

The gateway accepts the existing single-node `/etc/gway-mcp/execute.json` unchanged, or the following operator-owned multi-node form:

```json
{
  "enabled": true,
  "nodes": [
    {
      "node": "gway-001",
      "address": "REPLACE_WITH_ENROLLED_WG_IP",
      "ssh_host_alias": "gway-001",
      "known_hosts": "/var/lib/gway-mcp-exec/known_hosts",
      "identity_file": "/var/lib/gway-mcp-exec/relay_identity",
      "host_key_sha256": "REPLACE_WITH_ATTESTED_HOST_KEY_SHA256_HEX",
      "remote_user": "gway-relay"
    },
    {
      "node": "gway-002",
      "address": "REPLACE_WITH_ENROLLED_WG_IP",
      "ssh_host_alias": "gway-002",
      "known_hosts": "/var/lib/gway-mcp-exec/known_hosts",
      "identity_file": "/var/lib/gway-mcp-exec/relay_identity",
      "host_key_sha256": "REPLACE_WITH_ATTESTED_HOST_KEY_SHA256_HEX",
      "remote_user": "gway-relay"
    }
  ]
}
```

**These values are placeholders, not deployment-ready configuration.** Populate them from trusted Watchtower enrollment and operator-provisioned SSH material, never from an MCP client request. Each alias must have exactly one pinned entry in the private known_hosts file. The relay public key must be authorized for the forced-command protocol on each node. The gateway process must be able to read the root-provisioned private material without making it world-readable. Do not copy 001's host key fingerprint to 002.

The gateway validates registration, attestation, reachability, grant, and pinned address when loading configuration and again checks current eligibility before each dispatch. A missing configured transport fails closed. Preserve 001 as a configured node during rollout. Restart the gateway after atomically installing the updated root-owned configuration; test `node_exec hostname` on both nodes and verify `node_result`. If the new gateway cannot start, restore the previous single-node configuration and restart.

## Export the existing Watchtower relay **client** public key

On the trusted Watchtower local console, with the current CLI release
installed, run:

```sh
sudo gway-remote watchtower relay-public-key gway-001
```

This local-only command reads the existing root-controlled
`/etc/gway-mcp/execute.json` to select the **SSH client identity**
already configured for `gway-001`. It reads no private key bytes into
stdout, never generates a key, never changes the configuration, and does
not open an SSH connection. It refuses unknown nodes and unsafe
configuration/key metadata; root is required. If `gway-001` is not
configured, do **not** substitute its *host* key or the WireGuard key.
Use a different already configured relay node only after verifying that
it is the identity intended for `gway-002`.

Example *shape* (values are not a real key):

```json
{"node":"gway-001","public_key":"ssh-ed25519 AAAA...","sha256":"64-lowercase-hex-characters"}
```

The checksum is SHA-256 of the canonical ASCII public-key line **plus
one terminal LF newline**. It is the digest expected by the text-only
`gway002-connect.sh stage` process, not the SSH host-key blob digest
recorded in Watchtower's attestation. The key itself is safe to transfer,
but the result is still intended for the authorized operator console,
not logs, issue comments or public dashboards. Never print or transfer
the matching private key.

Note that `gway-remote host-key` exports the **local SSH server host
key**, which is completely different. The new subcommand is available
only after the corresponding PR is reviewed, merged and deployed to the
Watchtower CLI runtime; CI alone does not update Watchtower.
