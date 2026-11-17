# Android MCP provider: first increment (#339)

A single **gway-001** USB Android device is available through the existing
node-owned MCP federation (no direct Watchtower ADB, new daemon, credential,
privilege, or SSH identity). This is independent of the GWay Android app.

## Tools

After the reviewed GWay Remote runtime is deployed on gway-001 and the
owner-managed `android.json` manifest is published, the public tools are:

| Tool | Scope | Behavior |
| --- | --- | --- |
| `android__status` | `gway:read` | Model and screen dimensions; no serial exposed |
| `android__ui_tree` | `gway:read` | At most 100 visible elements; password nodes omitted |
| `android__capture` | `gway:read` | One JPEG preview, scaled to 480 px width |
| `android__tap` | `gway:execute` | Tap an in-range pixel coordinate |
| `android__swipe` | `gway:execute` | Swipe in range with bounded duration |
| `android__key` | `gway:execute` | BACK, HOME, ENTER, WAKEUP, SLEEP only |
| `android__text` | `gway:execute` | Small restricted ASCII strings, **not secrets** |

The provider rejects zero/multiple ADB devices, unauthorized devices, and
TCP/emulator-only connections. It selects the single authenticated USB device
and never accepts a caller-supplied serial. This is a device-selection rule,
not another OAuth or Linux authorization authority. No root, unlocking,
installation, reboot, network ADB, generic `adb shell`, or arbitrary file path.

All actions have strict input schemas plus node-side validation. Executions
remain restricted to the existing `arthe` installation user. The Android
screen can expose personal/private information: callers must not paste captured
images or UI text into GitHub issues, diagnostic logs, or public artifacts.

## Rendering and bounds

Capture invokes Android `screencap -p`, converts in-memory with the existing
`/usr/bin/ffmpeg` to a bounded JPEG, and returns one standard MCP image.
Watchtower preserves **only** a validated, bounded JPEG response as an image;
all other providers retain their historical JSON-text wrapper. UI inspection
uses Android `uiautomator dump`, parses the XML into a short whitelist of
fields, and removes the transient device file.

The node provider manifest is published by the GWay Remote runtime playbook,
not by the legacy source-policy convergence. It refers to the immutable
runtime SHA, with the real Python interpreter `/usr/bin/python3.11`.
Providers belonging to AgentOps, Odoo, and other owners remain untouched.

## Test and acceptance

Hermetic:
```sh
python3 -m unittest -v tests.test_mcp_android_device
python3 -m unittest discover -s tests -v
```

No CI job may require hardware. After CI and review, explicitly deploy the
approved release to **gway-001 only**, then refresh the connected plugin
catalog and verify:

1. `android__status` returns the expected model/dimensions with no serial.
2. `android__capture` renders an actual image (not text/base64).
3. `android__ui_tree` lists only visible non-password elements.
4. With the screen already unlocked, one deliberate `tap` and `key=BACK`
   work with `gway:execute`, while read-only tokens cannot execute actions.
5. Unplug/replug recovers without USB permission dialog. No other nodes,
   phones, host services, or unrelated repos are affected.

Do not claim installed MCP availability until this field acceptance succeeds.
This increment does not implement browser scenarios, image-redaction pipelines,
persistent screenshots, or automation loops; those remain separate #339 work.

## Stage 2: state and coordinate metadata (#339)

The existing seven MCP tools, USB-only device selection, federated transport,
\`gway:read\`/\`gway:execute\` annotations and input schemas are unchanged.

- \`android__status\` adds \`screen_on\` (display power ON), \`locked\`
  (current Android user's trust state) and \`rotation\` (degrees:
  0/90/180/270). Each may be \`null\` when vendor dumpsys output is
  unavailable or cannot be interpreted; do not treat unknown as unlocked.
- \`android__ui_tree\` adds boolean \`checked\`, \`selected\`, \`focused\`
  and \`scrollable\` to each existing, password-redacted element.
- \`android__capture\` keeps exactly one 480px-wide MCP JPEG image content
  and adds standard MCP \`structuredContent\` with \`native_width\`,
  \`native_height\`, \`capture_width\`, \`capture_height\`, \`scale_x\`,
  \`scale_y\`. The source dimensions come from the PNG captured in that
  same call, not an earlier screen query. The scale maps preview pixels
  to native coordinates: \`native_x = preview_x * scale_x\` and likewise
  for Y. Round to integers and validate screen bounds before tapping.
  Older one-image responses remain valid; clients ignoring
  \`structuredContent\` still receive the same image.

No auto-wake, unlock, new tools, authentication, services, scenarios,
persistent images, or additional device access are introduced.

