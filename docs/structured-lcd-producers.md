# Fleet and Deploy Broker LCD notices — staged rollout

Source of contract: [gway-lcd-sound#74](https://github.com/arthexis/gway-lcd-sound/issues/74).
Only **three** producers are in scope: AgentOps (in its own repo), fixed-node
fleet health, and existing deployment notifiers/receipts. Do not create a
new notification server.

## Fleet: read-only independent observer on gway-001

The `gway_remote.fleet_lcd_notifications` timer checks only explicitly approved
node/service tuples through existing SSH identities and pinned host keys:

| Target | Account | Evidence |
| --- | --- | --- |
| gelectriic.com (WT) | ubuntu | nginx.service, gway-mcp-gateway.service |
| ocpp-abb-1 (ABB1) | ubuntu | ocpp-csms.service, ocpp-reports-ingest.service, ocpp-reports-collector.service |
| gway-004 (004) | arthe | fixed `true` command for pinned SSH reachability, never service state |

These are initially *read-only*. gway-002 is not DNS-resolvable from 001 and
gway-005 lacks an accepted pinned SSH host key at the audited preflight; neither
may be declared offline by this observer. Any new node requires separately
verified host enrollment/trust and an explicit reviewed target list change.

Every check yields `healthy`, `down` (remote systemctl specifically inactive),
`unreachable` (SSH unreachable) or `degraded` (indeterminate result).
Two consecutive bad observations are required for a new incident, and two
healthy observations for recovery. A startup baseline is silent. The private
state journal is written **before** sending any LCD/Sound output; a failed
delivery or crash is never replayed as a new sound. Active incidents renew
their 120s LCD lease without repeat audio.

Install `deploy/systemd/user/gway-fleet-lcd.{service,timer}` under the
gway-001 installation user. `PYTHONPATH=/opt/gway-mcp/current` loads the pinned
release; it uses `lcd notice` and `sound` from that same user's established
LCD/Sound installation. Verify systemd syntax and the exact source revision
before enabling the timer. First cycle baselines; after two confirmed failed
probes the incident is displayed. No synthetic network or node failures in
production. A read-only preflight may use `--once --dry-run`; dry-run does not
write private state or emit a notification.

Rollback: `systemctl --user disable --now gway-fleet-lcd.timer`, then allow
notifications to expire. Do not disable unrelated MCP health services.

## Deploy Broker: source, destination and subject are separate

`DeploymentSound(target, node=..., repository=..., deployment_id=...)`
retains the existing SQLite deduplication of `(attempt,app,node,event)`.
The new typed LCD view uses `target_node` for the deployment **destination**,
`origin_node` for the real executor, and a full `arthexis/repository` subject.
A new attempt may begin; stale events never replace later attempts.

When structured LCD is enabled, legacy anonymous `lcd-event-deployment.lck`
writes are replaced by `lcd notice`, with no fallback after an uncertain
remote route. Sound remains owned by the existing `DeploymentSound` player.
Activation is not verification. A manual recipe returning zero maps to
`deploy-activated`, and only independently verified installed revision
plus positive health evidence may generate `deploy-verified`. Unknown broker
outcomes generate no final success/failure sound.

To opt in locally after receiver acceptance, create an **owner-only 0600**
`~/.config/gway-remote/lcd-notifications.enabled` containing `enabled`.
Alternatively set `GWAY_DEPLOY_LCD_NOTIFICATIONS=1` in the trusted executor.
The Watchtower `gway-mcp-gateway` account is distinct from the already
authorized `ubuntu` LCD/Sound source: **do not copy Ubuntu's bearer**, grant
the gateway generic execution, or silently enable manual broker notices
until an independent authenticated source path is accepted. The bridge already
validates `lcd.notice`, but a source without its own verified grant is denied.

## Security

On remote delivery, `gway_remote.lcd_sound_source_policy.authorize`
requires the entire internal `origin_node` to equal the Watchtower-verified
source principal's configured `source`, then the new explicit
`lcd.notice` operation must exist in its grant. No credentials, command
fragments, output logs or long free-text errors enter notification payloads.
All statuses are source-evidenced. Incident IDs and receipt IDs are bounded
and stable. The receipt audit remains the authority for the operational state.
