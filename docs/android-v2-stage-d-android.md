# Android v2 Stage D — passkey integration and controlled rollout

Tracking: [#378](https://github.com/arthexis/gway-remote/issues/378), [#381](https://github.com/arthexis/gway-remote/issues/381).
This increment adds native Android Credential Manager with **no automatic activation** of Watchtower's privileged issuer.

## Components

- Android MCP Access is a local HOME entry, never an `OperationRegistry` backend
  command. It discovers `GET /admin/v1/capabilities` on a **pinned** HTTPS host.
  No direct IP, cleartext, arbitrary endpoint, OAuth session, app preference
  token, shell command, or unverified backend token may authorize passkeys.
- Credential Manager registers WebAuthn `webauthn.create` with a one-use
  Watchtower console grant, then signs a **fresh** `webauthn.get` challenge
  for every combined-bearer issue and every targeted revocation.
- The bearer is only returned by Watchtower after a verified UV assertion,
  exists only in transient Android UI memory and is not written to disk.
  It is hidden after a one-time copy and, while the app remains alive, the
  clipboard is conditionally cleared after 60 seconds. The Android OS may
  independently retain clipboard history: operators should paste it
  promptly and clear their keyboard/provider clipboard history.
- The sensitive panel sets Android `FLAG_SECURE` against screenshots,
  screen sharing and recent-apps snapshots while it is open. Physical QA
  screenshots can show the normal home and **disabled/closed** state only.

## D1: deliberately separate administrative HTTPS activation

`watchtower_webauthn_admin.AdminHandler` listens only on
`127.0.0.1:19014`; public Nginx cannot be enabled by this PR's ordinary
Ansible release. The example `deploy/mcp-bearer/nginx-passkeys.conf.disabled`
is **not installed** by any workflow; it is an operator-reviewed server
snippet for the existing *TLS* virtual host `remote.arthexis.com`.

Before enabling:

1. Obtain and independently verify the SHA-256 **signing certificate**
   fingerprint from the **actual release-signed APK** (not the APK checksum).
   Run `python3 scripts/render-passkey-assetlinks.py
   --signing-cert-sha256 XX:... --output /tmp/assetlinks.json`.
   This prints a public `android:apk-key-hash:<base64url>` origin.
   Do not invent a certificate fingerprint, add a debug signing key, or
   rely on GitHub release numbers as an identity.
2. Check that the Android Digital Asset Links statement includes package
   `com.arthexis.gwayremote` and the exact certificate fingerprint. Install
   it under the pinned HTTPS host as
   `/.well-known/assetlinks.json` with **200, application/json, no
   redirects**, and validate with Android's Digital Asset Links tooling.
   The app manifest points to that same URL.
3. In protected Watchtower administrator runtime configuration, pin
   `GWAY_WEBAUTHN_ANDROID_ORIGIN=android:apk-key-hash:...`, set the
   existing `GWAY_WEBAUTHN_ADMINISTRATORS` allowlist, enable
   `GWAY_WEBAUTHN_ISSUER_ENABLED=1` and launch the isolated
   `watchtower_webauthn_admin serve-issuer` command under the authorized
   Watchtower admin. **Never** launch it under Mobile API, MCP verifier,
   an arbitrary node, or the general deploy service.
4. Review the TLS host's pre-existing Nginx `location` precedence and
   authentication, and only then include the disabled snippet manually
   in the existing HTTPS server. It forwards **only** explicit administrative
   routes to the private listener, normalizes upstream Host/Origin, avoids
   request-body logging, blocks unknown routes and never publishes port 19014.
   Perform `nginx -t` and a controlled reload. Add a server-level request
   rate limit and WAF policy appropriate to the host before public exposure.
   If a public trusted reverse proxy forwards to Watchtower, do not enable
   it until its identity and access-control boundaries are reviewed.
5. Check `GET https://remote.arthexis.com/admin/v1/capabilities` reports
   `passkeys_enabled=true` **only** with both privileged issuer injection
   and an exact Android origin configured. Disabled/absent must stay
   fail-closed. No bearer tokens, grant values or credentials in logs.

## D2–D3: operator experience

Open **MCP Access** on Android. Supply the administrator ID (only its
allowlisted value is permitted) and a **one-use, 10-minute enrollment grant
created at the trusted Watchtower terminal**, obtained out of band, never
through a chat or issue. Select *Enroll passkey*. Credential Manager's
platform UI creates a passkey; Watchtower accepts only cryptographically
validated registrations.

Once registered, choose *Issue read + execute bearer*: a fresh UV-required
assertion binds both scopes and a 24-hour requested lifetime. The returned
bearer is shown behind a password-style field, one time; *Copy once* puts
it on Android's system clipboard and hides the field. The next issuance
uses a different challenge and creates an independent bearer, not a replay.
The *Revoke bearer with passkey* action accepts only a 24-character token ID
and signs its own new action-specific challenge. An issue does not
implicitly revoke earlier tokens.

**Recovery** remains the trusted Watchtower console and passkey revocation,
not an Android local fallback. A lost device requires revoking its passkey
credential and, if warranted, revoking separately all potentially leaked
bearer parent IDs. No self-enrollment or self-reset is provided.

## D4: physical QA plan on gway-001

1. PR CI: Kotlin/Gradle unit tests and release build; Python 3.10 ES256
   verification with Android signer-origin fixtures, disabled-host tests
   and Digital Asset Links rendering contract.
2. After merge, let the normal release workflow sign the APK, download its
   exact release `Source-Commit`, install with `adb install -r` on the
   USB Android device connected to `gway-001`.
3. Before activation, verify home contains MCP Access and tapping it
   presents **Unavailable**, while System, Deployments, Agent Ops,
   GitHub Health and secondary tools still work. Capture screenshots
   outside the sensitive panel; never capture passkeys, grants or bearer.
4. Only after operator-approved issuer activation and association:
   test enrollment with a real passkey, fresh issuance, paste to the
   existing OAuth flow, verify both read and execute, replay rejection,
   revoke one bearer, verify descendants lose access, test lockout/error
   handling, and restore a disabled issuer when finished.
5. If the physical Android has an outdated credential provider or Google
   Play Services and cannot invoke Credential Manager, record that as a
   **device compatibility blocker** rather than bypassing WebAuthn.

No production credentials should be created, copied into tools or revoked
during automated CI or an unapproved device smoke test. Keep issue #378
open until real operator-authorized D4 is demonstrated.

## Rollback

Close the MCP Access panel. On Watchtower, disable the dedicated
issuer, remove the explicitly installed Nginx administrative snippet,
test+reload Nginx and revoke only intentionally identified test tokens.
Existing MCP gateway and OAuth link services continue independently.
