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
