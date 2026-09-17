# Implementation plan

Status: planning baseline, 2026-09-17. Only milestone 0 is complete.
Future CLI commands, routes, and modules described here are design targets.

## 0. Establish the project — complete

- [x] Create the standalone repository.
- [x] Define first-release behavior and exclusions.
- [x] Record the architecture, synthetic example, and upstream references.
- [x] Break implementation into reviewable milestones with acceptance checks.

## 1. Classify one document without writing to Paperless

Build the Python package and CLI, typed internal records, a Paperless read client,
and the TypeSafe adapter. Fetch a selected document plus the allowed taxonomy;
submit document-type and tag questions together; emit a validated proposal to a
private local file. Start with a synthetic fixture before any real document run.

Add configuration for the Paperless URL/token, TypeSafe key/model, document
selection, and taxonomy descriptions. Resolve and record the tested server API
version and model identity. Lock dependencies after confirming current SDK behavior.

Acceptance checks:

- [ ] A synthetic invoice produces type and multiple tag suggestions end to end.
- [ ] Mocked Paperless tests cover pagination, authentication failures, deleted
  taxonomy entries, and missing OCR.
- [ ] Unit tests prove that the adapter uses Choice for one type and independent
  Noul questions for tags, without treating tags as mutually exclusive.
- [ ] Missing answers, invalid probabilities, oversized inputs, and provider
  failures produce actionable failures rather than successful empty proposals.
- [ ] Dry-run integration tests record zero Paperless mutation requests.
- [ ] No raw document text or credentials appear in ordinary logs.

Deliverable: inspectable proposals for a small, explicitly selected batch.

## 2. Measure accuracy and set a policy

Create a private, human-reviewed pilot of roughly 100–200 documents, stratified
across common types, uncommon tags, overlapping tags, poor scans, unknown types,
and documents where no tag applies. Include difficult cases deliberately.
Existing Paperless labels are candidate labels to verify, not unquestioned truth.

Separate calibration and held-out evaluation documents. Group duplicates and
closely related template families to avoid leakage between the two sets. Hide
target labels and manually revealing titles from classifier inputs during the
evaluation, and document the same input policy for production.

Acceptance checks:

- [ ] Report tag precision/recall by label and overall, type accuracy, review
  rate, eligible automatic coverage, p50/p95 latency, and cost per document.
- [ ] Include sample counts and uncertainty; avoid a single "accuracy" number
  dominated by correct negative tag decisions.
- [ ] Compare with existing Paperless matching on comparable held-out inputs
  where reproducible; report unavailable baseline data explicitly.
- [ ] Tune thresholds on calibration data, then assess the held-out set once.
- [ ] Sparse or poorly performing categories remain review-only.
- [ ] Version the policy and prompts; record exact model identifiers when available.

Deliverable: an evaluation report and proposed policy. Automatic mode remains off.

## 3. Persist proposals and build the review UI

Introduce SQLite migrations, a durable run ledger, and a small FastAPI/Jinja/HTMX
interface. Keep one application and one worker process at first. Provide queue,
document review, and run-history pages. Fetch OCR for review from Paperless on
demand instead of copying the whole archive into a second database.

Acceptance checks:

- [ ] Users can accept, edit, reject, and defer proposals using current taxonomy.
- [ ] A proposal distinguishes predicted labels, policy disposition, and actual
  applied changes; an accepted item is not presented as applied before write-back.
- [ ] A restart preserves pending reviews and reviewer corrections.
- [ ] Concurrent workers cannot claim the same job; duplicate submissions reuse
  completed decisions and recover interrupted work.
- [ ] Browser checks cover keyboard review, narrow screens, empty queues, and errors.
- [ ] The UI uses authenticated sessions and CSRF protection for mutations;
  credentials remain server-side.

Deliverable: a usable review app with apply disabled until milestone 4.

## 4. Apply reviewed changes reliably

Build a separate Paperless writer. Start with reviewed proposals. Add automatic
application only for fields covered by an evaluated policy. Re-fetch before
applying, validate taxonomy and the input fingerprint, then record each field
operation and verify its outcome.

Acceptance checks:

- [ ] Tag additions preserve tags added by users or other integrations.
- [ ] Existing document types are not overwritten automatically.
- [ ] Deleted/renamed labels, edited documents, changed policies, and stale
  approvals return to review without applying an obsolete decision.
- [ ] Tests inject timeouts before and after a successful write; reconciliation
  determines actual state before retrying.
- [ ] An accepted asynchronous task is not counted as completed without verification.
- [ ] Reapplying a completed proposal makes no additional changes.
- [ ] History contains before/after metadata and operation outcomes. A reviewed
  reversal proposal touches only attributable changes and checks for later edits.
- [ ] A staging Paperless instance verifies update and workflow behavior against
  its installed API, including concurrent-edit limitations.

Deliverable: reviewed write-back, followed by an optional evaluated automatic mode.

## 5. Run continuously in the homelab

Add opt-in polling of a dedicated queue tag, bounded batches, retry/backoff,
queue visibility, a stop-processing switch, health endpoints, and resource limits.
Persist queued jobs so restart recovery does not depend on an in-memory cursor.
Bound provider calls and input size; if an estimated run cost or document limit
is reached, stop scheduling new work and show the reason.

Package a non-root container with a persistent SQLite volume. Make deployment
changes in `home-ansible`, from its canonical checkout on scratch, after the
application is ready. Target `docker-server` with Podman/Quadlet, `services.network`,
a dedicated Caddy hostname, and a Homepage tile. Reload systemd before starting
the new Quadlet service. A successful health check must not depend on a paid model call.

Acceptance checks:

- [ ] Shadow-mode pilot on a selected queue changes no Paperless metadata.
- [ ] OCR processing and other classification writers have a documented ownership
  boundary; retries do not cause tag-triggered workflow loops.
- [ ] Removing a queue tag opts a document out before processing or apply.
- [ ] Secrets are injected at runtime; backups cover the database and taxonomy policy.
- [ ] Restart recovery, provider outage, restore, and rollback are exercised.
- [ ] `home-ansible` generated docs and `./check` pass before its commit and push.
- [ ] A limited deployment verifies Caddy, the review flow, and one approved change.

Deliverable: a small service that runs reliably and can be disabled independently.

## Immediate next work

Implement milestone 1 in this repository. It needs no homelab deployment changes.
Real-data validation will need a Paperless token and TypeSafe API key, supplied
outside git. This planning task has not fetched private documents or called Jev.
