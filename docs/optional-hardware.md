# Read-only local hardware inventory

Run locally on any GWay node:

```sh
gway-remote hardware
gway-remote hardware --json
```

This complements `gway-remote status` and `diagnose`, which report deployments
and service health rather than general host resources. The hardware command also
reports CPU architecture/count/current frequency, SoC temperature, device model,
RAM total/available/used percentage, uptime, and root filesystem capacity/free
space/used percentage using Linux procfs/sysfs and standard library reads.

All host fields are best-effort and nullable if a source is absent or unreadable.
There is no assumption that the host is a Raspberry Pi; on systems without Pi
specific interfaces, those fields stay null. The system model or RTC sensor
must not become a deployment prerequisite.

The command inspects Linux's registered `/sys/class/rtc/rtc*` devices
and the optional DS3231-compatible temperature sysfs input under
`/sys/bus/i2c/devices/1-0068/hwmon/hwmon*/temp1_input`.

The output includes the RTC driver, current hardware clock's UTC reading (if
exposed), and the kernel's `hctosys` flag when available. The flag only reports
whether that RTC initialized the system clock at boot: it **does not prove**
time synchronization accuracy or RTC battery health.

Ambient temperature is the RTC package's local reading, **not** the Raspberry
Pi SoC temperature nor necessarily outdoor temperature. The module does not
probe arbitrary devices or fall back to the SoC sensor.

This is entirely optional hardware. Machines without an RTC or the temperature
sysfs interface return `unavailable` with null readings and **exit successfully**.
They do not become unhealthy and no deployment gate changes. Unexpected missing,
malformed, or inaccessible readings are ignored.

The diagnostic uses read-only sysfs/procfs files and filesystem statistics; it never calls `hwclock`, modifies
Linux time, configures device-tree overlays, or initiates raw I²C transactions.
No systemd unit, restart, or additional dependency is introduced.

This is a **local CLI** command. It is not an MCP tool yet; exposing it through
an approved read-only node inspection interface is separate from granting
general remote execution.
