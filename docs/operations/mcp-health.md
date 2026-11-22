# MCP health and recovery evidence

Watchtower's `gway-mcp-health-monitor.timer` runs independently of the MCP
process every minute. Its latest private sample is
`/var/lib/gway-mcp-monitor/latest.json`; a failed sample makes the systemd
oneshot fail and records fixed failure classes in the journal. The sample
checks gateway, OAuth and private bridge process state, gateway restart count,
and gateway/OAuth loopback HTTP status. It does not establish ChatGPT access.
A restart burst needs two samples and systemd may reset its restart counter.
The monitor also publishes a root-owned, world-readable projection containing
only schema, sample time, and `ok` or `failed` in
`/var/lib/gway-mcp-monitor-public/status.json`. A failure remains visible for
five minutes, so two slower external probes can observe a short failure. The
authenticated `node_list` response exposes only the fixed status; missing,
unsafe, or more than three-minute-old projections are `unknown`.

The activation playbook writes root-only diagnostic files in
`/var/lib/gway-mcp-deploy/receipts`. Each run has a random correlation ID and
separate `before` and `rollback` records. They contain allowlisted systemd
properties and an error class inferred from a bounded recent journal window,
never journal text, request parameters, credentials or peer configuration.
A healthy rollback requires successful restoration steps and both gateway and
OAuth loopback checks. An incomplete restoration is reported unhealthy even if
the listeners still answer. Neither result proves public authentication or a
federated provider works.

For a separate machine, `ansible/playbooks/mcp-external-monitor.yml` installs
an authenticated, read-only public `node_list` probe and timer. The playbook
requires an existing root-owned mode 0600 read-only OAuth credential file at
`/etc/gway-mcp-monitor/oauth.json`. It neither provisions nor copies
credentials. The observer rotates its own OAuth refresh token using a durable
pre-request marker. If the response or durable write is uncertain, it refuses
to replay the one-use refresh token and requires reprovisioning. A missing,
expired or revoked credential yields a failed observer status. The monitor
reports the parent credential as expiring seven days before its recorded expiry;
the parent must then be reprovisioned. Do not use the
private backend bearer as public authentication. The external observer's
systemd journal shows only a fixed status class; it does not log tokens, HTTP
responses, URLs or node data.

The unprivileged `gway-mcp-health-alert.timer` observes the external probe's
systemd result without accessing its OAuth file or calling MCP itself. It
also detects a disabled timer, a stuck check, or a stale result. Two distinct
failed checks generate a fixed LCD event and warning sound; ongoing failures
repeat no more than once every 15 minutes. Two distinct successful checks
produce one recovery event and sound. A pending check never counts as recovery.
The five-minute local failure hold can delay recovery notification even after
Watchtower's immediate health has returned. Existing sound mute settings are
respected. The alert is local to gway-001 and is not an off-host notification.

Use `systemctl --user status gway-mcp-health-alert.timer` and
`journalctl --user -u gway-mcp-health-alert.service` to inspect the alert
observer. `~/.local/libexec/gway-mcp-health-alert --test failure` and
`--test recovery` issue clearly labelled local LCD/sound test events without
changing health state; they refuse to overwrite an active real alert. These
commands exercise the output path but human observation is still needed to
prove the screen was readable and sound was heard.

The temporary exclusion of gway-004 from Watchtower's execution configuration
was reverted after the per-node isolation deployment. A configured pin does
not make the node eligible while its current inventory checks fail.
