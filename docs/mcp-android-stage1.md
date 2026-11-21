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
`gway:read`/`gway:execute` annotations and input schemas are unchanged.

- `android__status` adds `screen_on` (display power ON), `locked`
  (current Android user's trust state) and `rotation` (degrees:
  0/90/180/270). Each may be `null` when vendor dumpsys output is
  unavailable or cannot be interpreted; do not treat unknown as unlocked.
- `android__ui_tree` adds boolean `checked`, `selected`, `focused`
  and `scrollable` to each existing, password-redacted element.
- `android__capture` keeps exactly one 480px-wide MCP JPEG image content
  and adds standard MCP `structuredContent` with `native_width`,
  `native_height`, `capture_width`, `capture_height`, `scale_x`,
  `scale_y`. The source dimensions come from the PNG captured in that
  same call, not an earlier screen query. The scale maps preview pixels
  to native coordinates: `native_x = preview_x * scale_x` and likewise
  for Y. Round to integers and validate screen bounds before tapping.
  Older one-image responses remain valid; clients ignoring
  `structuredContent` still receive the same image.

No auto-wake, unlock, new tools, authentication, services, scenarios,
persistent images, or additional device access are introduced.


## Stage 3: semantic targeting and settle verification (#339)

The two additional tools run in the existing node-owned USB provider only:

| Tool | Scope | Safety |
| --- | --- | --- |
| `android__tap_target` | `gway:execute` | One exact, unique `resource_id`; verifies unlocked, powered screen, rotation, enabled/clickable node and bounds; dispatches one tap only |
| `android__wait_ui` | `gway:read` | Checks a named state (`present`, `absent`, `checked`, `selected`, `focused`, `enabled`) in at most two fresh UI trees with up to 800 ms delay |

For tap verification, provide `expect_id` and `expect_state` together; optional `wait_ms` controls the single delay before the second observation. Without the expectation, a successful action returns `verification: unverified`, not confirmed. With it, the result is `confirmed`, `timeout` or `unknown`. This API does not retry the tap. A partial tree never proves a target unique or absent, and a locked/off/unknown screen or rotation change rejects a touch.

This is a no-autowake design. Never send sensitive UI identifiers or production screen captures to logs, pull requests or GitHub. The next increment will add operator-reviewed scenario IDs, private receipts and bounded execution; there is no generic ADB shell or browser automation here. Hardware testing is **opt-in**, not CI.

## Stage 4: reviewed scenario runner and private receipts (#339)

The installed Android node-owned MCP provider now also exposes:

| Tool | Scope | Contract |
| --- | --- | --- |
| `android__scenario_preview` | `gway:read` | Only an immutable, reviewed scenario ID; metadata and spec SHA-256, no device action |
| `android__scenario_run` | `gway:execute` | Execute one reviewed scenario with preconditions and a bounded action count; no caller-supplied steps |
| `android__scenario_result` | `gway:read` | Read one private, sanitized receipt by an exact 32-character opaque receipt ID |

The current reviewed catalog is deliberately small:
`usb-readiness-v1` (read-only USB health check) and
`home-screen-stability-v1` (one `HOME` key action only if the screen is
already awake and unlocked, followed by re-observation).
The latter is a **screen stability check**, not proof that any particular
app or dashboard opened.

Each `scenario_run` call has at most five immutable steps, at most two
actions, and never retries an action. The installed Python operation layer
continues to enforce USB-only device discovery, screen state, bounds and
strict ADB command allowlists. No arbitrary arguments, URLs, additional ADB
commands, external scenario files or shell access are accepted from ChatGPT.

A JSON receipt has a versioned schema, scenario ID, manifest SHA-256, coarse
step outcomes, action attempts, durations and a receipt hash. It is stored
at a fixed private location under the node installation user's home with
a 0700 directory / 0600 file and a bounded receipt count. The MCP response
exposes only the opaque receipt ID and hash. A caller may retrieve its
sanitized content with `scenario_result`. **No screenshots, UI strings,
serials, credentials, or other private device content are persisted.**
Screenshots must remain disabled until a separately reviewed redaction
policy exists; no generated artifacts are automatically uploaded to GitHub.

CI uses fakes and exercises both benign and denied scenarios. It never
moves or wakes the physical Android. Field acceptance remains an explicitly
observed separate step, not triggered by a PR merge. Real UI-specific
scenarios should be added only after obtaining a current, safe target ID
and reviewing the scenario source.


## On-demand USB wake (post-#339)

The single authorized physical USB device on `gway-001` is available even
when its screen is initially off. Execute-only `android__tap_target` and the
reviewed `home-screen-stability-v2` scenario may dispatch **one**
`KEYCODE_WAKEUP` when `screen_on=false`. After waking, the provider reads
screen power, lock and rotation again, then applies the usual unique-target,
clickability and bounds checks. A failed/unknown wake is **never retried**;
no PIN, credential, lock bypass, app install or network ADB is permitted.

`android__status`, `android__wait_ui`, capture and UI-tree inspection remain
read-only and never wake the phone. Existing scenario IDs, especially
`home-screen-stability-v1`, retain identical immutable steps and hashes.
The v2 preview advertises **at most two actions**: one conditional wake and
one `HOME`. A private receipt records actual successful wake invocations;
if a wake attempt returns an uncertain error, the attempt is conservatively
counted as one possible action. No screenshots or private UI text are stored.

CI tests use only fakes for awake, asleep, locked, unknown, wake failure,
changed display and no-repeat behavior. Real USB actions are operator-driven,
not part of PR CI. This does not create new OAuth scopes, MCP tools or services.
