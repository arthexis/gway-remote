# Archive: stage 1 integration design

Status: design only; no runtime behavior changes.

## Product behavior
- Archive and QR Scanner are **separate buttons** in the existing operation palette.
- Each opens an independently managed panel; multiple panels can remain open.
- Archive lists, filters, views and deletes saved records.
- QR Scanner owns camera lifecycle and QR decoding. It can open/copy decoded content or save the exact payload and original camera image.
- QR Scanner saves directly through the archive backend; Archive panel need not be open. If it is open, refresh its data without resetting either panel.
- Other panels may later expose **Save result**, independent of Archive's visibility.

## Verified code integration points
- `gway_remote/api.py`: `ThreadingHTTPServer`, authenticated `GET /api/v1/health`, `GET /api/v1/commands`, `POST /api/v1/execute`. Bearer authentication uses constant-time comparison. Request JSON cap is 8192 bytes; response JSON cap is 1 MiB. Keep those caps for existing endpoints. Do not embed image bytes in execute JSON.
- `gway_remote/mobile.py`: `commands()` advertises operations and their argument/read-only contracts; `execute()` is the mobile command dispatch boundary. Add archive metadata commands through this allowlist, not arbitrary SQL or shell.
- `android/README.md`: documents `OperationRegistry.kt`, `OperationPanels.kt`, independent panel state, palette and explicit execution policies. Follow these conventions rather than introducing a second navigation model.
- `android/app/build.gradle.kts`: Kotlin, Compose, minSdk 26, targetSdk 35; camera scanning dependency/permissions must be evaluated before implementation.
- `.github/workflows/ci.yml`: Python 3.11 test matrix with mobile group; Android test/build and backend deployment are separate release gates.

## Proposed backend boundaries (stage 2)
- `gway_remote/archive.py`: SQLite record/attachment metadata and transactions. A connection per operation; bounded transactions and busy timeout.
- Persistent state under a dedicated application state/data directory on Gway-001, not a checkout, release directory or transient workspace. Confirm deployment user, filesystem permissions and backup policy before choosing final path.
- Records: id, created_at UTC, source, kind, title, JSON data. Attachment metadata: generated ID, record ID, MIME type, size, managed filename; bytes stored outside SQLite with atomic publication.
- Existing authenticated execute route for bounded metadata operations: archive-list, archive-get, archive-save, archive-search, archive-delete. Define exact schemas before coding.
- Separate authenticated bounded binary upload/download endpoints for photographs. Stream payloads with strict size/type limits; do not raise the global JSON cap. Prevent path traversal, orphaned files and partial records.
- Search by metadata and textual fields initially; no semantic index, no new database service.
- Avoid duplicating CSMS's operational database. Archive stores user-selected snapshots only.
- No arbitrary SQL, filesystem paths, URLs executed by QR payloads, or automatic archive writes from every operation.

## Android boundaries (stages 3–4)
- Register distinct `archive` and `qr-scanner` operations with stable IDs.
- Archive panel fetches saved items and can show mixed content types.
- QR panel uses Android camera/decoder with explicit permission, capture and save; camera resources release when scanning stops/panel closes.
- Preserve original captured image (not just regenerated QR). Distinct scans can create distinct records even with identical payloads.
- QR content may be non-URL or binary. Opening a URL is explicit and separate from saving.
- Add a Save result action to operation output without requiring Archive panel to be open.

## Acceptance and test map
1. Backend: authorization, schema validation, pagination, search, persistence across process restart, independent SQLite connections, concurrent writes, duplicate QR captures.
2. Attachments: upload/download auth, size limits, invalid MIME, interrupted upload, missing attachment, deletion, path traversal, no partially committed record.
3. Android: palette opens both panels, independent state/close/reorder, no camera auto-run on panel open, explicit permission and capture, Save result, refresh open Archive after save.
4. Deployment: preserve SQLite and attachment directory across zipapp updates/rollback, verify owner permissions and backend compatibility before dependent APK publication.

## Open verification items
- Inspect the actual Kotlin source package paths and networking client before implementation; README documents components but does not establish their current signatures.
- Confirm `mobile.execute` dispatch details, API tests, and the actual service account/data path.
- Decide attachment upload protocol, record/attachment transaction semantics, backup/retention, and maximum image size.
- Confirm Android camera API choice and permission behavior on supported versions.

Stage 1 does not create a database, endpoint, panel or camera functionality.

## Verified Kotlin class-level integration (inspection follow-up)

- `OperationRegistry.kt`: `OperationSpec(id, label, icon, keywords, policy, command)`; IDs must be stable kebab-case and unique. Add separate `archive` and `qr-scanner` specs. Archive read may be `AUTO_READ` with `archive-list`; QR scanner must **not** be `AUTO_READ`, since opening a panel must not activate the camera.
- `OperationPanels.kt`: `OperationPanelState.open()` places new panels first and prevents duplicate IDs. `close()`, `move()`, `start()/complete()/fail()` and revision tokens isolate state and reject stale responses. `restore()` does not rerun operations. Keep QR camera lifecycle separate from this pure immutable state model.
- `OperationPalette.kt`: renders independent `OutlinedCard` panels and palette buttons from `state.unopened(filter)`. It has explicit specialized branches for task, simulator and CSMS panels. Add `ArchivePanel` and `QrScannerPanel` composables here (prefer separate files) and callbacks for archive actions. No new top-level navigation needed.
- `MainActivity.kt`: `CompanionScreen` owns `panelState`, opens panels via `OperationPalette.onOpen`, runs auto-reads with `runPanelRead`, and executes explicit operations via callbacks. Wire archive list/refresh and QR save here, preserving revision checks and independent open panels. Closing QR panel must release camera; panel close alone currently just removes state.
- `ApiClient.kt`: `request(path, command?, arguments?, timeoutMs?)` supports authenticated HTTPS JSON only, disallows redirects, and validates host/protocol. Add explicit bounded binary transfer methods; do not retrofit photo uploads into JSON or permit cross-host redirects.
- `gway_remote/mobile.py`: `execute(name, arguments)` is a closed if-chain and `commands()` advertises schemas. Archive handlers should validate types/keys per command and be explicitly registered. Existing default `OPERATIONS` path rejects any arguments.
- `gway_remote/api.py`: currently only GET health/commands and POST execute. Attachment routes need deliberate routing and authorization; avoid expanding the global 8 KiB JSON request limit.

### Revised implementation decisions
1. Add two palette buttons, not a new navigation section. Multiple panels stay open; QR saves without opening Archive.
2. Add a typed Archive panel that parses structured results, not a raw JSON dump. Its list refresh can be signaled after successful save while preserving other panel state.
3. Implement QR scanner as an interactive Compose panel with explicit start/stop, permission handling and camera disposal. Opening the panel must not launch permission or camera automatically.
4. Keep archive operation results and attachment transfer distinct in the client. The existing `ApiClient.request` remains unchanged for existing commands.
5. Preserve `OperationPanelState` as pure model; avoid storing camera resources, image bytes, or network handles in it.

### Additional test targets
- `OperationRegistry`: unique stable IDs and correct non-auto policy for QR.
- `OperationPanelState`: Archive and QR simultaneously open; closing one preserves the other; stale results ignored after reopen.
- `OperationPalette`: correct specialized panel selection and independent refresh.
- `ApiClient`: upload/download host validation, bearer authorization, bounded transfer, no redirects.
- `mobile.execute`: explicit archive command allowlist and invalid arguments rejected.
