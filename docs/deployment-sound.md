# Deployment audio

GWAY Remote emits source `gway-remote` through the existing user-local `sound`
player. LCD Sound owns the motif, sound mapping, mute and playback lock.
Install the companion LCD Sound release before expecting these events to play;
unknown events in older players remain silent.

The dispatch motif is G4–G5–D5 (392–784–587 Hz), with a 45-second context
cooldown. Source changes follow the player's existing reannouncement policy.

| Event | Sound | Evidence |
| --- | --- | --- |
| deploy-started | busy | CI/admission/lock gates passed; executor starts |
| deploy-activated | notice | Installer returned; backend executable installed |
| deploy-verified | ok | Active requested revision plus positive registered health probe; backend authenticated health and executable integrity |
| deploy-failed | error | Installer, restart, or required verification raised |
| rollback-started | warning | Backend recovery starts |
| rollback-verified | ok | Backup restored byte-for-byte, service active, authenticated health passes |
| rollback-failed | critical | Backend recovery or verification raised |

Batch, selected-target and manual executions share the hooks. Missing revision
or health evidence leaves the installation acknowledgement neutral. Existing
health probes define software acceptance, never physical-device acceptance.
Stage-only Bastion emits start/failure, but no activation or success sound.
Rollback events are emitted only by the backend transaction that owns recovery;
child installers' internal rollbacks are not guessed. Report-export jobs emit
no deployment success sound.

Each executor creates an attempt ID. SQLite deduplicates `(attempt, target,
event)` across notifier instances; explicit retries use a fresh ID. Receipts
older than seven days are deleted on emission. A receipt is claimed before
playback, so unavailable audio is not retried. Calls time out after three seconds
and cannot change deployment outcomes. No credentials or installer output enter
sound arguments or receipts.

The existing LCD event-lockfile runner receives the target, short revision and
state for 30 seconds. Audio/LCD errors are ignored. Set
`GWAY_REMOTE_SOUND_DISABLE=1` to disable these notifications and optional audio
verification probes, including during hermetic tests.

No new services, privileged playback helpers, or report-export hooks are needed.
