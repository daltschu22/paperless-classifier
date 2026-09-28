# Operations

## Starting and stopping

Run one Uvicorn worker per data directory. `/healthz` checks database access and worker liveness without querying external providers. Pause in the UI to let the active job finish while preventing further work. Automatic intake is off until explicitly enabled.

The homelab service is `paperless-classifier.service`. Its root-owned environment file is `/opt/services/paperless-classifier/classifier.env`; the database is `/opt/services/paperless-classifier/data/classifier.sqlite3`. Do not print the environment file or include it in diagnostics. Stop or restart with systemd; in-flight jobs become explicit retry/reconciliation entries on startup.

Use **Remove from queue** on a card to move its entry to History. Paperless documents and existing metadata are kept. Select the document again from the library to classify it later. A running provider request may finish, but removal prevents the next inference step and late results cannot put the item back in the queue. Approved changes can be canceled while waiting for the writer; removal is unavailable during an active write. Closing a failed application preserves any partial changes and its audit history. The sidebar badge counts all queue items; the library's review statistic counts only ready proposals.

With title/subject enrichment enabled, the generative model discovers subjects from document text without receiving the taxonomy. Review every suggested match to an existing tag; broader categories and narrower subjects can both be useful. Select a subject to reuse a tag or create a new one, and edit the new name if needed. Up to three new tags can be created in one approval. Existing definitions are retained. Jev-only mode skips discovery and vocabulary matching.

## Backups and restore

Use SQLite's online backup API for a live database, not an isolated copy of the main file while WAL is active. The homelab's existing app-backup role discovers SQLite files beneath `/opt`, creates consistent verified snapshots, and includes the classifier automatically. Back up the environment file securely as well. Backups contain document excerpts and session data and must remain private.

For restore: stop the service, retain the existing data directory as a recovery copy, place a verified SQLite backup at the configured database path, remove only the matching stale WAL/SHM files from the restored copy, set ownership to UID/GID 10001 and file mode 0600, then restart. Inspect interrupted applications before reconciling; a restored database may predate Paperless changes. Session rows may be deleted from the restored database to require fresh sign-in.

## Errors

- **No OCR / unreadable scan:** use Read with vision or inspect the original in Paperless.
- **Input too large:** process in Paperless/manual review; this release does not silently trim content or select only some pages.
- **Provider unavailable:** retry explicitly. The app does not create an endless paid retry loop.
- **Provider content filter / refusal:** review the original in Paperless. The app does not use the partial transcription or automatically repeat the request. This does not indicate invalid credentials.
- **Provider output limit:** the response ended before the result was complete; review the original in Paperless. Partial text is not classified.
- **Invalid structured result / timeout:** retry explicitly or inspect the original. These errors are distinct from authentication/configuration failures.
- **Stale document or taxonomy:** close the failed proposal without undo, then classify the document again against current state.
- **Proposal changed:** another tab or retry replaced the proposal. Close and reopen the review before applying; older forms cannot approve a replacement.
- **Pending or interrupted application:** reconcile approved changes. The app reads actual state before repeating writes.
- **Previously confirmed changes were edited:** close the failed entry without undo, then review a fresh proposal. Reconciliation does not reapply confirmed writes over later edits.
- **Unconfirmed tag creation with no match:** inspect Paperless for the earlier outcome, then close the entry and review a fresh proposal. The same uncertain create is not automatically repeated.
- **Duplicate tag name:** resolve normalized-name duplicates in Paperless, then reconcile.

A failed application may have changed some fields or created an unassigned tag. The history and operation journal preserve that fact; closing a failed proposal is not rollback. Correct unwanted changes in Paperless. Keep competing enrichment writers off the documents you are reviewing.

## Limits

Eight vision pages, 20 MiB original file, 60,000 text characters, six discovered subjects, three new tags per approval, ten selected documents per request, 50 processing jobs, latest 200 terminal history entries displayed, and twelve-hour sessions. All active reviews/errors remain visible regardless of history size. Semantic vocabulary matching supports 254 eligible tags and the bounded request size; it adds a Jev call when subjects lack exact name matches. Inference cache/history persist until the operator manages retention; no automatic pruning or spending cap ships in this release. The intake fingerprint deliberately retains the queue tag and skips unchanged input.
