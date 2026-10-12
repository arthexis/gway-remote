# Android phone-to-Pi benchmark

Open **Benchmark** in the Android app, choose Echo, Status, or Both, then run
bounded sequential samples. Echo measures authenticated HTTP round trips with
minimal Pi work; Status executes the normal read-only status command. Warmups
are excluded. The phone measures full request RTT with a monotonic clock. The
server returns monotonic command execution duration; the echo operation also
returns its internal processing duration. **Never interpret RTT minus processing
as one-way network latency.** Connection setup, serialization, and network
variation are included.

For AP versus LAN versus remote comparisons, connect the phone through the
desired path, enter a descriptive connection label, and run the same sample,
warmup, timeout, and payload settings for each route. Compare median and p95
RTT, failure counts, and server execution separately. Repeat runs to account
for changing network conditions. Connection labels are operator-supplied, not
automatically inferred.

After a run, **Copy JSON** copies the full structured measurements. **Share**
uses Android's share sheet. **Copy report + open issue #32** copies a Markdown
summary containing the raw JSON and opens the tracking issue in GitHub; paste
the clipboard text as a comment and submit it. This intentionally does not
automatically post comments or require a GitHub credential on the phone or Pi.

Reports include a unique run ID, UTC timestamp, endpoint hostname, operator
connection label, app version, parameters, counts, and timing samples. They
never include the bearer token, URL credentials, or request headers. The
endpoint hostname is included to identify the node; review the report before
posting if your hostname is private.

The runner is cooperative: cancellation prevents further requests, but an
in-flight HTTP call can take up to its configured timeout. Partial results
remain available. Status benchmarking is read-only; mutating commands are
not accepted by the benchmark runner.
