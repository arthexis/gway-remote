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
