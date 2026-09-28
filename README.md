# Paperless Classifier

A working, self-hosted review app for Paperless-ngx, powered by TypeSafe Jev and an optional generative model.

**Jev handles classification. Paperless supplies OCR. A generative model suggests titles and new tags, and reads scans when OCR is missing or poor. Every metadata change requires review.**

## What it does

- Browse and search Paperless; queue up to ten documents at a time.
- Classify each existing tag independently and choose a document type, with an unknown option.
- Suggest titles and discover up to six filing subjects from document text without supplying a fixed vocabulary. Jev suggests equivalent existing tags and independently scores every subject. Reviewers can reuse tags, rename new tags, or leave subjects unchecked; at most three new tags can be created per approval.
- Read PDF/image pages with vision when needed, or explicitly retry with vision.
- Review, edit, apply, dismiss, or defer proposals. Existing tags are preserved.
- Remove queued, running, ready, or failed items directly from the queue; entries remain in History and documents stay in Paperless.
- Persist jobs, inference cache, approved changes, and an operation journal in SQLite.
- Bind approvals to the exact displayed proposal and reconcile interrupted writes against actual Paperless state. Confirmed tag identities and writes are preserved; later conflicting edits require a fresh review.
- Optionally watch a dedicated intake tag. Automatic intake prepares proposals; it does not approve them.

This is a useful replacement for Paperless-GPT's title/tag/type workflow. It does not replace Paperless OCR, rewrite original files, create searchable PDFs, select correspondents, or automatically apply unreviewed predictions. Paperless-GPT can remain available for its other features.

## Run locally

Requires Python 3.12 and a Paperless API token that can read documents and taxonomy, edit document metadata, and create tags.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
# Set URLs and credentials in .env.
.venv/bin/uvicorn classifier.web:create_app --factory --host 127.0.0.1 --port 8098 --no-access-log
```

Open `http://127.0.0.1:8098`. Sign in using the Paperless account associated with the configured token, or that token directly. This is a single-account application: other Paperless accounts are not granted the service account's document access.

Set `APP_ORIGIN` to the exact browser origin, including scheme and port. Behind HTTPS, the app uses a Secure, HttpOnly, SameSite session cookie. Credentials remain on the server. Store the data directory on a local filesystem, not NFS, and run one worker per database.

`OPENAI_API_KEY` enables titles, subject discovery, and vision through the Responses API. With no generative key, select Jev-only processing. Models default to `jev-1.13.0` and `gpt-5.6-sol`; both are configurable. TypeSafe receives document text for classification and subject/tag definitions for vocabulary matching. Discovery sends document text without the taxonomy to OpenAI; vision sends rendered document pages. OpenAI requests use `store=False`.

Discovery runs for every document with enrichment enabled, even when broad existing tags fit confidently. Equivalent names can reuse existing IDs; broader or narrower concepts remain distinct suggestions. All discovered subjects stay visible so reviewers can correct the suggested matches. Matching is a separate Jev call when subjects lack exact name matches; model quality on the real archive remains unmeasured.

## Container

```bash
podman build -t localhost/paperless-classifier:local -f Containerfile .
# Prepare a private, writable /data volume for UID 10001.
podman run --rm --env-file .env -e DATA_DIR=/data   -p 127.0.0.1:8098:8000 -v ./private/app-data:/data   localhost/paperless-classifier:local
```

The homelab deployment is managed separately in `home-ansible` using Podman Quadlet, a private Caddy hostname, and persistent `/opt/services/paperless-classifier/data` storage.

## Verification

```bash
./check
# Optional real browser check; uses synthetic Paperless and model providers only.
.venv/bin/pip install -r requirements-browser.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python tools/browser_smoke.py --screenshots private/browser-smoke
```

The shared check runs offline tests and the original research harness dry runs. Tests cover authentication, CSRF, independent classification, vocabulary matching, reviewer overrides, caching, atomic approval revision checks, preserved tags/definitions, recovery conflicts, active jobs beyond the history limit, poor OCR, queue-removal races, and invalid provider responses. The browser smoke also exercises new-tag renaming, existing-tag reuse, and an old review tab submitting after another tab regenerates the proposal. See [build validation](docs/build-validation.md) for current results and the separate historical live provider checks.

## Read more

- [Product outline](OUTLINE.md)
- [Implementation status and follow-ups](PLAN.md)
- [Architecture and recovery](docs/architecture.md)
- [Operations](docs/operations.md)
- [Initial Jev investigation](docs/investigation-2026-09-17.md)
- [Source notes](docs/sources.md)

Independent project; not an official Paperless-ngx or TypeSafe product.
