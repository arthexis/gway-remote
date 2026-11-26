# Android navigation model

The Android provider exposes the read-only `navigation_model` tool. It inspects
the current unlocked, awake device through the existing USB provider and returns
a recognized screen, known controls and, optionally, a suggested route to a
reviewed destination. For example, request `{"destination":"developer_options"}`.
The currently reviewed graph covers Spanish Samsung Settings, Settings search,
and Developer options, including the state of **Permanecer activo**. It was
observed on an SM-G950F; other versions and languages may not match.

Each route step gives a source, destination and human-readable instruction. The
route is directional and may be unavailable, even for a known destination.
An unknown, ambiguous or truncated tree never identifies a screen; an unclear
switch association omits its state. The model does not write screen contents,
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
