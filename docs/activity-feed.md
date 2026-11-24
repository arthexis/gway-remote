# Activity Feed — Stage 1A (#705)

The feed is a quiet activity history, not an LCD/Sound notification mechanism.
This stage provides an isolated Python library; no CLI, HTTP, MCP or Android
integration is enabled. Watchtower will own the central database and admission.

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
