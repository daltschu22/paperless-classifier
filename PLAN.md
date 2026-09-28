# Implementation plan and status

Updated 2026-09-27. The initial planning repository is now a working hybrid classifier application.

## Completed

- [x] Paperless read client with pagination, restricted write methods, safe error handling, and bounded downloads.
- [x] Jev Choice for document type plus independent Noul questions for existing and proposed new tags.
- [x] Validated answers, explicit unknown type, input limits, and model/usage provenance.
- [x] Optional generative titles, new-tag suggestions with evidence, and full-document vision fallback within size limits.
- [x] SQLite jobs, sessions, cache, tag definitions, intake cursor, approvals, and write-operation journal.
- [x] Authenticated responsive review UI, CSRF protection, search, selection, deferred items, and history.
- [x] Reviewed write-back with stale-input checks, additive tags, live name deduplication, and reconciliation after ambiguous responses.
- [x] One-worker lock, persistent restart recovery, optional intake, pause control, health endpoint, and non-root container packaging.
- [x] Offline failure/recovery tests and synthetic end-to-end browser checks.
- [x] Live synthetic Jev, generative title/new-tag, and vision API checks.
- [x] First-principles review fixes: atomic proposal-bound approvals, durable confirmed write identities, preserved curated definitions, all active jobs visible, and the poor-OCR gate in Jev-only mode.
- [x] Open-ended discovery without taxonomy input, explicit Jev synonym matching, visible reviewer overrides, new-tag renaming, and existing-tag reuse. New matching behavior has synthetic offline coverage; live quality remains unmeasured.

Evidence for the review fixes and discovery milestone is recorded in [build validation](docs/build-validation.md). Earlier live checks predate the discovery/matching change.

The UI and writer shipped together because the requested scope became a complete application. The original CLI-first sequence was a planning proposal; the web queue now provides the selection and proposal workflow.

## Deployment acceptance

Use the canonical `home-ansible` checkout for the limited docker-server deployment. Pin an app commit, inject credentials, configure Quadlet/Caddy/Homepage, regenerate homelab documentation, and run the full infrastructure check. Validate authenticated read access and a proposal without applying changes to existing archive documents. Record outcomes in [build validation](docs/build-validation.md).

## Next milestones

1. **Private evaluation:** curate real archive labels, separate calibration and held-out documents, and compare predictions with Paperless matching. No automatic application before an evaluated policy exists.
2. **Writer integration coverage:** add an isolated Paperless staging instance to CI, including delayed bulk tasks and update-triggered workflows. Current ordinary tests exercise a synthetic Paperless adapter.
3. **Higher-volume operation:** paginated history beyond the latest 200 terminal entries, configurable spending limits, exponential retry scheduling, cache retention, and operator metrics. All active jobs remain visible. Current jobs require explicit retry and the processing backlog is capped at 50.
4. **Richer filing:** correspondent selection, longer-document handling, and more precise candidate descriptions.
5. **Reviewed reversal:** construct a new proposal from attributable changes, with fresh conflict checks. Current history supports inspection and manual correction in Paperless; it does not offer undo.

The initial [investigation](docs/investigation-2026-09-17.md) remains historical evidence, not a claim about current real-document accuracy.
