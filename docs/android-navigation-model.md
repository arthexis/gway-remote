# Android navigation model

The Android provider exposes the read-only `navigation_model` tool. It inspects
the current unlocked, awake device through the existing USB provider and returns
a recognized screen, known controls and, optionally, a suggested route to a
reviewed destination. For example, request `{"destination":"developer_options"}`.
The currently reviewed graph covers Spanish Samsung Settings, Settings search, search results,
and Developer options, including the state of **Permanecer activo**. It was
observed on an SM-G950F; other versions and languages may not match.

Each route step gives a source, destination and one human-readable action. Search entry and result selection are separate transitions. The
route is directional and may be unavailable, even for a known destination.
An unknown, ambiguous or truncated tree never identifies a screen; an unclear
switch association omits its state. Recognition is package-scoped; the switch must share a nearby structural ancestor with its title, not merely coordinates. Two successive semantic observations and device-state checks must agree. This detects observed changes, not every transient transition between captures. The model does not write screen contents,
discover controls automatically, perform taps, wake or unlock the device.

Before each action, inspect the current screen using `ui_tree` or `capture`.
Use existing semantic actions where a unique actionable resource ID is present;
otherwise resolve coordinates from the current observation. After one action,
observe again and verify the expected destination or state. Do not replay old
coordinates or act on an unrecognized screen. To set a switch, inspect its
current value first and act only if it differs from the desired value, then
confirm the result. Treat unexpected screens or uncertain results as a stop.
The returned model contains only reviewed screen and control identifiers, not
the full tree, arbitrary labels, or screenshots.

To extend the graph, review screen markers and directed transitions in
`gway_remote/android_navigation_model.py`, add deterministic tests for
ambiguity and incomplete trees, and verify the observed screen on an authorized
physical Android within the requested scope. Do not add private screen content.


## Scenario integration

Use `scenario_preview` before `scenario_run`. The reviewed
`developer-options-from-search-v1` scenario starts on the recognized,
focused, empty Spanish Settings search screen. It enters the fixed query,
verifies search results, selects a unique enabled clickable result by resource
ID or a structurally verified clickable ancestor row, and verifies Developer options.
The empty search screen may contain recent searches; the saved-query header
is distinguished from the Developer options result breadcrumb. Anonymous rows
are retained only in the internal navigation snapshot, never the public UI tree.
The internal row resolver requires a shared nearby ancestor, no competing
interactive descendants, valid containment, and identical structural targets
and bounds in two fresh observations. It does not expose arbitrary coordinate
or ancestor selectors to callers. It performs at most two actions, never
wakes the device or toggles a setting, and stops on uncertainty without
retrying an action. Opening Settings search is still an advisory/manual edge.
`developer-options-observation-v1` only asserts the recognized screen.
Both scenarios run under the existing execute scope; previews and receipts
remain read-only. Receipts contain operation names and outcomes, not UI data.

Existing scenario IDs and recipes are unchanged. New scenarios may use
`navigation_model` assertions and the internal `semantic_transition` operation
for reviewed executable edges only. Do not accept caller-supplied recipes,
selectors, destinations or arbitrary search text for scenario execution.

### Physical transition attribution

Real provider calls that interact with the device acquire a nonblocking private
cross-process lock for the entire operation, including the full scenario. Busy
calls fail without input; preview and receipt retrieval remain available. This
coordinates provider calls, not physical touches or external ADB clients.
Semantic transition receipts record a sanitized dispatch classification and
allowlisted failure reason. Zero invocations means a pre-dispatch refusal,
not proof that the UI did not change independently. An ADB error after the
invocation boundary counts conservatively as one uncertain attempt, never a
retry. Destination verification permits at most three observations and requires
two consecutive matching destination observations and unchanged device state.
Old receipts and immutable scenario specifications remain readable and unchanged.

### Bounded invocation tracing (diagnostic-only)

For Android calls the existing Watchtower-generated, authenticated node request
ID becomes the stdio tools/call JSON-RPC ID. No extra request field, new tool,
caller-supplied trace ID, scope, credential or transport is introduced. The
node and Watchtower annotate only scenario-run responses with their matched ID
and bounded elapsed time. The receipt's hash covers the provider/runner evidence;
the transport annotations are separate response evidence, not part of the hash.

Each new real scenario receipt includes at most 32 allowlisted monotonic stage
events: provider entry and lock, runner entry/steps/finish, preflight screen
classification and empty/focused/enabled field flags, target resolution, dispatch
readiness, actual ADB input subprocess attempt/return/error and post-observations.
A private node-owned file holds at most eight recent provider input attempts
within the preceding ten minutes, using only invocation ID, reviewed tool and
input kind. It is updated under the existing device lock, and no raw text,
selector, bounds, serial, screenshot, raw subprocess arguments or credentials
are stored. Storage errors or truncation mark evidence incomplete. Existing
receipts remain readable, and the reviewed recipe and action budget are unchanged.

Compare the invocation ID in the run response, node/Watchtower annotations and
independently retrieved receipt before attribution. Zero invocations with a
first preflight already recognizing the destination and no input-attempt marker
shows that this provider call did not reach its ADB input boundary; it does not
identify physical touches, external ADB clients or other non-provider input.
Do not treat such a discrepancy as a successful transition, relax authorization,
or retry uncertain input. The recent marker history is bounded and cannot prove
the absence of uninstrumented input. No Android publication is required.
