# USB Android canary: independent Mobile API device credential

Tracking: #669. This is the **Mobile API** at \`https://remote.arthexis.com/api/v1/*\`,
not the OAuth/MCP bearer used by ChatGPT or the Watchtower passkey issuer.

## Credential model

- The existing \`GWAY_REMOTE_API_TOKEN\` is left unchanged.
- Per-device random 256-bit bearer is issued **only in memory on gway-001**,
  never printed. Only the ID, label, scope, expiry and revocation flag are stored
  in operational receipts. The user-owned SQLite registry under
  \`~/.config/gway-remote/mobile-device-credentials.sqlite3\` is mode 0600,
  in a 0700 owner directory, and stores **SHA-256 hashes**, not plaintext.
- Device label \`gway-001-usb-canary\`, read-only scope, 30-day expiry.
  Safe GETs and explicitly read-only POST operations are permitted; mutating
  operations receive 403. This is a dedicated *bearer*, not hardware-backed
  cryptographic attestation; a copied plaintext would still authorize until
  expiry/revocation. Never call this a non-copyable token.
- Revoke solely by the public ID as the installation user:
  \`python3 -m gway_remote.mobile_device_tokens revoke PUBLIC_ID\`.
  \`python3 -m gway_remote.mobile_device_tokens list\` shows only metadata.
  Revocation is checked per request; no global mobile API rotation required.

## One-shot physical handoff (canary package ONLY)

1. Keep a **same-repository open PR** with the reviewed Android test.
   Manually run \`.github/workflows/android-canary.yml\` with that PR number
   and its exact current full HEAD SHA, and require a green result. This does
   not happen on ordinary backend merges.
2. Download the paired artifact with GitHub CLI on **gway-001**. Verify
   \`PROVENANCE.txt\`, \`SHA256SUMS\`, run origin, PR head, APK package names
   and unchanged production-app path. The node-owned script applies the
   same fail-closed checks before issuing anything.
3. Execute **once**, as the installation user, the bounded
   \`python3 -m gway_remote.android_canary_provision --pr PR_NUMBER
   --sha EXACT_SHA --run-id ACTIONS_RUN --artifact-dir PRIVATE_DIRECTORY\`.
   Use a user systemd unit with a timeout if calling through a bounded
   remote executor. The CLI arguments are public metadata only.
4. The script permits exactly one authorized physical USB device, refuses
   emulators, wakes but never unlocks it, temporarily preserves the USB
   display-awake setting with exact restoration, and installs *only* the
   isolated canary and canary-test APKs. A recognized canary signature
   conflict may reset **canary-only** data; the signed production app and
   credentials are not installed, uninstalled or modified.
5. Once the new canary/test APKs are verified, the script mints an exclusive
   token, writes it via ADB \`exec-in\` **stdin** to a private \`run-as\`
   file in the canary sandbox (no token in process arguments) and invokes
   only \`MobileDeviceProvisionTest\`. That test deletes the private file,
   encrypts the bearer using AndroidKeyStore/SecretStore and makes a real
   authenticated **HTTPS GET /api/v1/health**. The script then runs the six
   hermetic Compose component checks. The result prints only a public token
   ID, expiry, scope, source SHA, CI run and pass/fail counters.
6. On any incomplete provisioning/test result, the node revokes the newly
   issued credential and attempts private-file cleanup. If a catastrophic
   node failure prevents revocation, use the local \`list\` and \`revoke\`
   commands above against the public ID. Never print bearer values.
7. Reopen the canary and inspect System and CSMS using the dedicated Android
   MCP tools; the absence of \`Token is required\` and successful read-only
   operations are separate real UI acceptance criteria.

## Security boundaries

Do not use \`android__text\` to enter tokens, log authentication headers,
put a token in a GitHub issue, command argument, screenshot, environment
variable in a job log, clipboard, or ChatGPT tool result. Do not use Watchtower
MCP bearer issuance for the Mobile API. Do not treat a 401 without a token as
an outage. The legacy server token remains effective for its existing users.

The canary is a debuggable test package. The USB handoff relies on authenticated
physical ADB and \`run-as\`, **not** a publicly exposed provisioning endpoint.
Do not enable this path for production APK, an emulator, other nodes, untrusted
USB clients or unattended enrollment. Do not enable Android canary polling/timer
as part of this test.
