# Activity Feed stage 7 — controlled canary, NOT activated

## Preconditions
- All seven Draft PRs reviewed, stacked changes integrated in a reviewed candidate
  without merging main; pin SHAs. Separate authorization required to install.
- Confirm installed account and actual Watchtower gateway service ownership.
  Use existing installation identity, no new UID, sudo grant, or execute token.
- Create private 0700 state and backup directories on a dedicated quota-backed
  filesystem. 0600 database/credential files. Enforce OS hard quota covering
  DB + WAL + SHM + backups; SQLite page budget alone is not a total quota.
  Suggested separate central volume 512 MiB, producer volume 128 MiB, backup
  volume 512 MiB; confirm headroom and filesystem support before activation.
- Prepare root-owned exact grants, no wildcard; audit via feed-maintenance
  audit-grants. Verify root and delegated token revocation, scope isolation,
  source/node/repository/type mismatch, disabled routes and no bearer in URL.
  Issue only feed-publish to producers, read to mobile. No secrets in logs.

## Hermetic canary before field authorization
1. Temporary SQLite stores and loopback gateway, synthetic CloudEvents, separate
   scoped test credentials; replay, conflict, concurrent writers, expiry,
   invalid input and unavailable receiver. No real business data.
2. Simulate lost response and restart flusher; exactly one receipt, no primary
   operation failure. Fill quota, verify explicit refusal and recovery.
3. Run backup and restore-new to a separate private directory; compare receipts,
   sequence and quick_check. Never replace a running database or restore old
   cursors without resetting clients. Restore can regress sequence and omit
   later dedup receipts: pause producers, reconcile pending events and client
   cache before any authorized switch.
4. Test isolated user provision twice, no changes second time; activate only
   temporary test timer, verify stop and cleanup. No live service changes.
5. APK canary isolated from production, use read-only temporary credentials,
   validate offline expiry, revocation, navigation and no push/sound.
6. Measure DB/WAL/SHM, queue age, retries and dead counts; monitor via local
   status, never emit feed events from maintenance itself. Prune daily in
   bounded batches of <=1000 by receipt age; checkpoint passive; repeat if
   backlog exists, no automatic VACUUM.
7. Rollback: stop test timer and gateway, revoke only test credentials, delete
   only isolated test state; preserve actual queue, backups and production APK.

## Operational limitations
- max_page_count caps database pages; WAL admission guard is conservative, not
  a hard bound under concurrent readers or checkpoint starvation. A real
  dedicated filesystem quota and free-space measurement are mandatory.
- Backup/restore-new never switches an active store. Review snapshot age and
  reconcile before any real recovery. No retention of backup files automatic.
- Stage 6 recovery-card wrapper pinned to inspected executable hash; no card
  has been written or checked. Offline verification does not attest boot.
- No production ingress/proxy routes, grant provisioning, systemd activation,
  physical quota setup, canary install or backup job has been executed.

The central database is created exclusively in a pre-existing private owner directory by `gway-remote feed-maintenance --database PATH init`; repeating it validates the same existing store and never chmods or replaces it. Schedule `prune` daily using the existing authorized account's systemd user manager only after validating its actual identity; the sample inactive units use a private EnvironmentFile at `%h/.config/gway-remote/feed-maintenance.env` containing only the absolute database location. Do not install them on a producer-only node. Producer `feed --status` includes queue age, retry count, next due and physical file sizes; no payload or identity is returned. The backup wrapper is a separate opt-in operator entry point, not a replacement of the root-owned backup utility.
