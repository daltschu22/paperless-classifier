# Build validation — 2026-09-17

## Offline and browser

- Shared `./check`: 37 passing tests plus both synthetic investigation dry runs.
- Browser smoke: Chromium, 1440px desktop and 390px mobile. Login, queue, review, new-tag selection, apply, history, tag definitions, and pause passed with no browser errors or mobile horizontal overflow.
- Failure tests cover stale content/metadata/taxonomy, asynchronous tags, timeouts after successful creates/patches, duplicate submission, restart recovery, CSRF, authorization, and provider/input validation.

These tests use a synthetic Paperless adapter and make no network calls to Paperless or inference providers.

## Live providers, synthetic input

A synthetic solar invoice produced a title and three candidate new tags. Jev selected Invoice and independently scored the candidates 0.97, 0.73, and 0.28. Enrichment took 7.05 seconds (325 input / 171 output tokens); Jev took 0.378 seconds (651 input / 118 output tokens). A synthetic invoice image was transcribed legibly in 3.745 seconds (986 input / 72 output tokens).

Models: `gpt-5.6-sol` and `jev-1.13.0`. These are smoke checks of API integration, not accuracy estimates. Provider credentials and private artifacts remain outside git.

## Deployment

Deployment verification is recorded when the limited homelab rollout completes. No existing archive metadata is changed by these synthetic tests.
