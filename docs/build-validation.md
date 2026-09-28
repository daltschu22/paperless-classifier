# Build validation — 2026-09-17

## Offline and browser

- Shared `./check`: 40 passing tests plus both synthetic investigation dry runs.
- Browser smoke: Chromium, 1440px desktop and 390px mobile. Login, queue, review, new-tag selection, apply, history, tag definitions, and pause passed with no browser errors or mobile horizontal overflow.
- Failure tests cover stale content/metadata/taxonomy, asynchronous tags, timeouts after successful creates/patches, duplicate submission, restart recovery, CSRF, authorization, and provider/input validation.

These tests use a synthetic Paperless adapter and make no network calls to Paperless or inference providers.

## Live providers, synthetic input

A synthetic solar invoice produced a title and three candidate new tags. Jev selected Invoice and independently scored the candidates 0.97, 0.73, and 0.28. Enrichment took 7.05 seconds (325 input / 171 output tokens); Jev took 0.378 seconds (651 input / 118 output tokens). A synthetic invoice image was transcribed legibly in 3.745 seconds (986 input / 72 output tokens).

Models: `gpt-5.6-sol` and `jev-1.13.0`. These are smoke checks of API integration, not accuracy estimates. Provider credentials and private artifacts remain outside git.

## Deployment

The limited rollout is live at <https://classifier.daltschu.com/>. The full home-ansible check and both repositories' initial GitHub CI runs passed. TLS, service health, unauthenticated rejection, Secure/HttpOnly cookies, authenticated library access, desktop/mobile review, and Escape-to-close were verified through the deployed hostname.

One selected real archive document produced a review proposal with 52 eligible existing tags scored. The original OCR contained substantial corruption despite exceeding the length heuristic. A follow-up readability gate detected that corruption and exercised the complete fallback on the real original: quality assessment → vision → enrichment → Jev. The calls took 4.062, 18.193, 1.661, and 0.779 seconds respectively. The vision transcription was retained only in the private proposal/cache, not written back to Paperless.

Before/after metadata comparisons confirmed zero metadata changes to that existing document. Intake remains disabled. This is a functional pilot, not a labeled accuracy evaluation. Real write behavior has synthetic integration coverage; no existing archive documents were used as write-test fixtures.

## Provider error handling — 2026-09-18

A reported scan failed after the vision provider returned an incomplete, content-filtered response containing unfinished JSON. The SDK raised a validation error before the app could inspect completion status, producing a misleading credentials/availability message. The adapter now checks status and refusal before parsing; incomplete text never becomes a classification proposal. The provider did not disclose the reason for filtering.

Six added offline tests cover filtered and token-limited partial JSON, explicit refusal, invalid completed output, timeout, successful parsing/usage, and the service boundary that prevents classification or writes after a filtered scan. Fixtures are synthetic and use the actual SDK over a mocked HTTP transport. See OpenAI's [structured-output edge cases](https://developers.openai.com/api/docs/guides/structured-outputs#step-3-handle-edge-cases).

The diagnostic dataset was one user-reported document; only private reports and an isolated diagnostic database were written. Credentials, provider responses, document content, and private evaluation artifacts remain outside git. No Paperless document metadata was changed.

## Review fixes and subject discovery — 2026-09-27

- Shared `./check`: 85 passing offline tests plus both synthetic investigation dry runs.
- The original five review findings have regression coverage: stale/replaced proposals, atomic approval transitions, confirmed tag IDs and metadata during recovery, active reviews beyond the history limit, preservation of curated definitions, and rejection of weak OCR in Jev-only mode.
- Older proposals and persisted approvals remain usable without a database migration. Browser approvals now include the revision captured when the review opened; old forms must be reopened after regeneration.
- Discovery uses the actual Responses SDK over a mocked HTTP transport to verify structured subject output and document-only input. No existing taxonomy is supplied to that call.
- Synthetic Jev responses exercise exact-name matching, semantic equivalents, distinct subjects alongside high-scoring broad tags, invalid matching answers, taxonomy limits, reviewer overrides, renamed labels, existing-tag reuse, cache provenance, and cancellation during matching.
- Chromium browser smoke passed at 1440px desktop and 390px mobile, including new-tag renaming, reuse of an existing tag, and an old review tab submitting after a second tab regenerated the proposal. Existing login, apply, history, settings, queue-removal and layout checks also passed, with no page errors.

These checks used synthetic text, adapters, and disposable local databases. They made no live provider calls or Paperless writes. The matching decisions in the tests are simulated: they establish application behavior, not real synonym accuracy or outlier recall. The historical live checks above predate this discovery pipeline; private evaluation and deployment validation of this revision remain outstanding.
