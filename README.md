# Paperless Classifier

A working, self-hosted review app for Paperless-ngx, powered by TypeSafe Jev and an optional generative model.

**Jev handles classification. Paperless supplies OCR. A generative model suggests titles and new tags, and reads scans when OCR is missing or poor. Every metadata change requires review.**

## What it does

- Browse and search Paperless; queue up to ten documents at a time.
- Classify each existing tag independently and choose a document type, with an unknown option.
- Suggest titles and up to three new tags with supporting document quotes. Jev independently scores the new tags; they start unchecked during review.
- Read PDF/image pages with vision when needed, or explicitly retry with vision.
- Review, edit, apply, dismiss, or defer proposals. Existing tags are preserved.
- Remove queued, running, ready, or failed items directly from the queue; entries remain in History and documents stay in Paperless.
- Persist jobs, inference cache, approved changes, and an operation journal in SQLite.
- Reconcile interrupted writes against actual Paperless state before reporting success.
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

`OPENAI_API_KEY` enables titles, new tags, and vision through the Responses API. With no generative key, select Jev-only processing. Models default to `jev-1.13.0` and `gpt-5.6-sol`; both are configurable. Selected document text is sent to TypeSafe; enrichment sends text and tag definitions to OpenAI, and vision sends rendered document pages. OpenAI requests use `store=False`.

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

The shared check runs 55 offline tests and the original research harness dry runs. Tests cover authentication, CSRF, independent tag classification, caching, stale approvals, preserved tags, new-tag deduplication, uncertain writes, restart recovery, input limits, document names on failed/queued jobs, queue-removal races, and incomplete/refused/malformed generative responses. The browser smoke checks login, review, new-tag approval, application, history, settings, mobile layout, document names, queue removal, and queue counts. Live provider smoke checks used synthetic text and a synthetic scan; see [build validation](docs/build-validation.md).

## Read more

- [Product outline](OUTLINE.md)
- [Implementation status and follow-ups](PLAN.md)
- [Architecture and recovery](docs/architecture.md)
- [Operations](docs/operations.md)
- [Initial Jev investigation](docs/investigation-2026-09-17.md)
- [Source notes](docs/sources.md)

Independent project; not an official Paperless-ngx or TypeSafe product.
