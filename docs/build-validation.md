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
