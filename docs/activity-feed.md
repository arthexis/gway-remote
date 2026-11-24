# Activity Feed — Stage 1A (#705)

The feed is a quiet activity history, not an LCD/Sound notification mechanism.
Stage 1A provides the isolated library. Stage 1B adds opt-in HTTP routes to
Watchtower's existing loopback bearer gateway. No CLI, MCP or Android integration
is enabled, and no production configuration is changed.

## Event contract

A restricted CloudEvents 1.0 JSON envelope: specversion, id, source, type, time,
data and optional subject. All other fields are rejected. Data requires title
(160 characters), summary (1024), category and severity (info/success/warning/error).
Optional fields: node, repository, commit, issue, pr, url, correlation_id.
Identifiers are bounded ASCII tokens; source and subject are bounded strings.
Timestamps must include an offset and are normalized to UTC microseconds.
Links are HTTPS without userinfo, query or fragment; UI must treat them as
untrusted and apply its own destination policy. No logs, secrets or customer
details; producers must enforce redaction, not rely on schema validation alone.
Canonical serialized size is capped at 16 KiB. Stage 1B must also bound raw
request size and JSON parsing before calling this library.

## Store semantics

Use a dedicated trusted local path (not user input). SQLite WAL, schema v1,
append-only events, auto-increment receipt sequence, UTC server receipt time,
and unique (verified producer, authorized source, id). The caller must
authenticate the producer and authorize source, node and visibility before
calling the store. This library only checks source equality and does not
perform authentication. Identical normalized replay returns the original
record; changed payload raises EventConflict. Per-operation connections and
immediate write transactions serialize races. No network or alert side effects.

list_after uses ascending receipt sequence, not event time, so delayed events
remain discoverable. Page limit 1–100, optional exact category filter.
Cursors are scoped to the same database and filter; clients must restart sync
on database replacement or filter change. No global visibility policy or
per-user read state yet. Future API must supply authorization and bounded
history paging separately.

Default row ceiling 200,000; insert fails explicitly at capacity, while
duplicates remain idempotent. prune removes at most 1,000 events per call,
using receipt age (default 180 days). Retained cursors are not reused; gaps
are expected. Replay after pruning can create a new sequence because no
tombstone is retained. Future outbox retry horizon must account for this.
No automatic pruning, byte quota, backup or migration scheduling yet.
SQLite may retain freed pages; physical disk limits and checkpoint/maintenance
policy are acceptance work before production. No changes to live configuration.

## Validation

Run python3 -m unittest tests.core.test_activity_feed -v and the repository
test suite. The core CI group automatically includes the new tests.
Stage 1B requires a separate authorization and ingress review.

## Stage 1B: authenticated HTTP (disabled by default)

- GET /api/feed/events: existing gway:read or gway:execute bearer. Defaults to
  latest receipts descending; before=<seq> continues that history. after=<seq>
  selects incremental ascending receipts. Optional category and limit (1–50).
- GET /api/feed/events/<seq>: same read permission, 404 for missing records.
- POST /api/feed/events: existing gway:execute bearer AND a live explicit grant
  for the stable authenticated principal. HTTP 201 insert, 200 replay, 409
  conflict, 403 denial, 413 oversized, 503 unavailable. Body <=16 KiB, strict
  UTF-8 JSON, duplicate keys rejected. No bearer IDs exposed in responses.
- All readers in this initial operator-only deployment see the same non-sensitive
  activity history. No per-user authorization or public sharing yet.
- Fixed root-owned /etc/gway-remote/activity-feed-sources.json uses the existing
  grant snapshot loader with schema 1 and grants keyed by stable principal ID.
  Each grant has exactly enabled, source, nodes, repositories, types. Lists
  are exact matches; null permits absent node/repository, never a wildcard.
  Reload on each publish. No credentials in grants or event bodies.
- Explicit opt-in GWAY_ACTIVITY_FEED_ENABLED=1 and dedicated absolute
  GWAY_ACTIVITY_FEED_DATABASE path; startup validates grants. Existing service
  and reverse proxy configuration remains untouched. No new scope or listener.
  Do not give producers execute tokens: stage 2 must define a constrained
  authenticated transport for external producers. Production activation needs
  reviewed path ownership, proxy limits, grant lifecycle and disk budget.
- Test via python3 -m unittest tests.core.test_activity_feed tests.core.test_activity_feed_http -v.

## Stage 2: local producer queue and restricted HTTPS

Use the existing Bearer registry with an exclusive operator-issued
gway:feed-publish scope and the same per-principal feed grant. It does not
imply read, execute or LCD/Sound. The existing local console script
scripts/mcp-bearer.py can issue it; never give an execute token to a producer.
No changes to public OAuth discovery, service units, or proxy routing.

Provision each existing installation user with private (0600)
~/.config/gway-remote/feed.json containing exactly endpoint (HTTPS Watchtower
/api/feed/events URL), source (authorized URI), node (default node or null),
and token_file (absolute path to a private 0600 scoped credential).
No token in arguments, event, outbox, or logs. No proxy or redirects.
The same command works on Watchtower and other nodes once configured.

gway-remote feed "Backup completed"
gway-remote feed "Deploy completed" --type deployment.completed --repo arthexis/ocpp-reports
gway-remote feed --json event.json
gway-remote feed --status
gway-remote feed --flush

An explicit --id requires --time for immutable producer retries. The standalone
feed wrapper is optional via GWAY_INSTALL_FEED_ALIAS=1 during installation,
not activated by this PR. Existing operator-managed timer/job may invoke
--flush; do not start a new daemon or deploy a timer in this stage.
Enqueue never connects to network; producer hooks use publish_best_effort or
ignore/report CLI failure without failing primary work. SQLite lock timeout
150ms per connection, full synchronous WAL, 2048 rows total, reject newest
when full, no silent eviction. Exact payload remains until receipt; repeat
delivery is safe across crash/restart. Single flusher via flock; retry with
5s exponential backoff up to one hour, batch <=20, HTTPS socket timeout 4s.
Bad payload/conflict is dead; auth/network failures retry for up to 30 days.
Dead items count toward capacity and require explicit --purge-dead; delivered
records expire on flush after 30 days. Do not change producer source or
destination while queued without explicit reconciliation. A root credential
rotation requires grant/identity migration; child rotation under the same
root preserves identity. Automatic provisioning/timer, ingress review,
physical disk budget and production activation remain acceptance work.
