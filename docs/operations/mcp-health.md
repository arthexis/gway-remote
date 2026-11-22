# MCP health and recovery evidence

Watchtower's `gway-mcp-health-monitor.timer` runs independently of the MCP
process every minute. Its latest private sample is
`/var/lib/gway-mcp-monitor/latest.json`; a failed sample makes the systemd
oneshot fail and records fixed failure classes in the journal. The sample
checks gateway, OAuth and private bridge process state, gateway restart count,
and gateway/OAuth loopback HTTP status. It does not establish ChatGPT access.
A restart burst needs two samples and systemd may reset its restart counter.

The activation playbook writes root-only diagnostic files in
`/var/lib/gway-mcp-deploy/receipts`. Each run has a random correlation ID and
separate `before` and `rollback` records. They contain allowlisted systemd
properties and an error class inferred from a bounded recent journal window,
never journal text, request parameters, credentials or peer configuration.
A rollback result checks the gateway and OAuth separately; it does not prove
that public authentication or a federated provider works.

For a separate machine, `ansible/playbooks/mcp-external-monitor.yml` installs
an authenticated, read-only public `node_list` probe and timer. The playbook
requires an existing root-owned mode 0600 OAuth access token file at
`/etc/gway-mcp-monitor/oauth-access-token`. It neither provisions nor copies
credentials and does not manage OAuth token renewal. A missing, expired or
revoked token yields a failed observer status, never a false healthy result.
Provision a narrowly scoped observer with an independently managed renewal
mechanism before enabling the timer. Do not use the private backend bearer as
public authentication. The external observer's systemd journal shows only a
fixed status class; it does not log the token, HTTP response, URL or node data.

The current temporary exclusion of gway-004 from Watchtower's execution
configuration should be reverted only after deploying and verifying per-node
isolation, and with the existing protected backup available. A restored pin
does not make the node eligible while its current inventory checks fail.
