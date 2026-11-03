# Raspberry Pi power flags in status

`gway-remote status` and `gway-remote status --json` include an optional
`power` object reporting the result of `vcgencmd get_throttled`.

The bitmask distinguishes current undervoltage, frequency capping, throttling,
and soft temperature limits (bits 0-3) from whether each has occurred since
boot (bits 16-19). Status is `ok` when all these flags are clear, `warning`
when any is set, and `unavailable` if the command is missing, unsupported,
times out, returns nonzero, or emits malformed output.

This is **observational only**. Warnings do not override the health of
deployment components, trigger restarts, or block operations. The check
does not require root access, runs with a two-second limit, and is silent on
non-Raspberry Pi hosts lacking `vcgencmd`.

A historical flag alone can be evidence of an earlier power problem and
does not mean the voltage is presently low; history is since the current boot,
not necessarily the lifetime of the device.
