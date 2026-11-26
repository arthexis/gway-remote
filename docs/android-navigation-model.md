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
ID, and verifies Developer options. It performs at most two actions, never
wakes the device or toggles a setting, and stops on uncertainty without
retrying an action. Opening Settings search is still an advisory/manual edge.
`developer-options-observation-v1` only asserts the recognized screen.
Both scenarios run under the existing execute scope; previews and receipts
remain read-only. Receipts contain operation names and outcomes, not UI data.

Existing scenario IDs and recipes are unchanged. New scenarios may use
`navigation_model` assertions and the internal `semantic_transition` operation
for reviewed executable edges only. Do not accept caller-supplied recipes,
selectors, destinations or arbitrary search text for scenario execution.
