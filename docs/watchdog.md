# Linux hardware watchdog

Read-only inspection (works without root and on sensorless nodes):

```sh
gway-remote status --json
gway-remote watchdog show
gway-remote watchdog show --json
```

The status JSON contains a separate `watchdog` object with systemd's
`RuntimeWatchdogUSec` and `RebootWatchdogUSec`, plus discovered Linux
`/sys/class/watchdog/watchdog*` devices, identity, current state, timeout,
and time remaining. A watchdog device being present does *not* mean it is
active. Missing sysfs entries or systemd yield `unavailable` / null fields,
not an unhealthy node. No new health or deployment gates are introduced.

On a machine with a supported device, local operator-only configuration:

```sh
sudo gway-remote watchdog enable --timeout-seconds 15 --apply
sudo gway-remote watchdog disable --apply
```

Supported requested watchdog timeouts: 15, 30, 60 or 120 seconds. **The driver
may clamp a requested timeout.** Confirm the actual value with
`gway-remote watchdog show`. BCM2835 firmware in particular may support
shorter timeouts than other drivers. Both actions require root and the explicit
`--apply` acknowledgment. No changes occur simply by deploying GWay Remote
or using `watchdog show`.

Configuration writes *only* the GWay-owned
`/etc/systemd/system.conf.d/90-gway-remote-watchdog.conf` drop-in using
atomic replacement, then invokes `systemctl daemon-reexec` to apply the
systemd manager setting. If that fails it attempts to restore the previous
owned drop-in and reexec again. It does not edit vendor systemd configuration,
change the boot device tree, or install another watchdog daemon. An unrelated
drop-in at that path is refused, not overwritten. Disabling writes
`RuntimeWatchdogSec=0` and does not change `RebootWatchdogSec`.

**Caution:** Enabling can cause an unexpected reset if PID 1 cannot feed the
watchdog. Use only with console or physical access and no active charging;
never enable it blindly on a production charging gateway. A successful
configuration action is not proof the hardware watchdog is running: inspect
the sysfs `state` and `timeout_seconds` after applying.

This local CLI is not exposed over MCP and must not be added to unattended
deployers. A hardware watchdog monitors systemd's liveness; it does not detect
all runaway applications or power failures.
