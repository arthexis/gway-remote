# Owner-bound federated providers (#777), stage A

The HTTP ingress derives a stable principal from the verified bearer and
effective read/execute scope. Only the reviewed aeon_score source opts in.
The selected route accepts this identity out-of-band, rejects reserved caller
identity arguments, and has no fallback to the legacy provider transport.
The node's legacy dispatcher rejects this provider. Existing providers retain
their exact legacy route and wire contract.

This stage deliberately does not implement invoke_principal, advertise a
provider, or provision credentials. Next, add distinct operation-bound read
and execute RPCs on the existing authenticated, pinned SSH channel. Bind the
principal, node, provider, tool, request ID and canonical argument digest at
the gateway. At the node, require the trusted gateway ingress, verify the
operation and all routing/digest bindings, and enforce bounded replay defense.
Pass verified context out-of-band to the fixed provider process. Never use a
caller argument or an unverified context digest as proof of identity. Test
receiver-first compatibility, malformed messages, replay and cross-owner
access before registration.

Threat boundary: this isolates MCP callers, not already authorized node
operators. The existing execute scope permits operator-level node shell
execution under the same installation account; such an operator can inspect
or modify local provider data and forge local process inputs. A cryptographic
digest or environment variable is not isolation against this operator.
Do not claim mutually hostile shell-operator isolation; achieving that would
require a separately approved change to the identity/authorization model.
No credentials or existing permissions are changed by this PR.
