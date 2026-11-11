# webOS TV automatic retry (gway-001)

The GitHub scheduler is opportunistic; it has not reliably fired every five minutes.
The existing `webOS TV automatic deployment` workflow still runs on schedule and
also after the backend `Deploy GWay Remote backend` completes successfully.
A small systemd timer on **gway-001 only** retries locally every five minutes;
it does not wake the TV, copy credentials, add a service account or alter OAuth.

Both paths call the same root-owned installed
`/opt/gway-remote/scripts/deploy-webos-tv.sh`, which obtains the exact main SHA
and **successful push CI** before changing either installation. Its shared
`auto-deploy.lock` makes simultaneous GitHub/timer invocations no-ops.

The node receipt `deployed.sha` means the node runtime/bridge passed Ansible
checks. The TV receipt `tv-installed-sha` is recorded only after both apps
were installed successfully, and after rechecking the reviewed SHA. The old
`auto-deployed-sha` is never trusted.

* Exit **10** from webOS install: TV webOS service on port 3000 unreachable
  (powered off, asleep or network unavailable). This does **not** prove it
  was physically powered off. No TV receipt; retry on next timer tick.
* Exit **11**: TV on webOS port 3000 is reachable, developer SSH (9922) is
  not. Developer Mode may have expired or been disabled. No TV receipt;
  retry automatically, but the operator may need to restore Developer Mode.
* Other nonzero: fail the runner/timer attempt; do not mask certificate,
  pairing, model mismatch, broken package or CLI errors.
* Exit 0: two successful installs and unchanged CI-gated SHA. A historical
  receipt cannot prove a later uninstall; inspect TV apps and build evidence
  before declaring complete.

Read-only diagnostics on the node: `systemctl status
gway-webos-auto-deploy.timer`, `journalctl -u
gway-webos-auto-deploy.service`, and SHA receipts under
`~/.local/state/gway-webos-tv/`. Never print or copy Developer Mode keys.
