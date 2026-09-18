# Architecture

```mermaid
flowchart LR
    P[Paperless OCR and taxonomy] --> R[Reader]
    R -->|Poor OCR or explicit retry| V[Generative vision]
    R --> G[Optional titles and new tags]
    V --> G
    R --> J[Jev classification]
    G --> J
    J --> S[(SQLite proposals)]
    S --> U[Authenticated review]
    U --> W[Writer and reconciliation]
    W --> P
```

Python 3.12, FastAPI/Jinja with plain browser JavaScript, SQLite, HTTPX, the official TypeSafe SDK, and the OpenAI Responses API. One worker thread processes jobs sequentially; a filesystem lock prevents two application workers from owning the same data directory. No broker or frontend build is needed.

## Providers and data

Paperless IDs identify existing taxonomy entries. Jev receives document text and tag/type definitions, without the current title or target labels. The type question is a Choice including `unknown`; each existing or newly suggested tag has its own Noul question. Missing answers, invalid ranges, nonfinite probabilities, unexpected options, and broken distributions fail closed.

A generative call optionally proposes a title and zero to three missing tags. Suggestions require supporting quotes present in the supplied text, normalized names, and no duplicates. Jev scores those suggestions alongside existing tags. None are created before explicit review selection.

OCR with fewer than 60 alphanumeric characters, or a high replacement-character ratio, triggers vision when enabled. When enrichment is enabled, its readability assessment also triggers vision for substantially garbled text that passes those simple checks. If vision is disabled, unreadable text becomes an explicit review error. Jev-only mode has the inexpensive text heuristic; a reviewer can explicitly request vision for other poor scans. PDFs and multipage images are rendered locally and all pages are supplied in order. Limits: eight pages, 20 MiB downloaded originals, 60,000 text characters, and a conservative 110,000-byte serialized Jev request. Oversized inputs fail visibly; input is never silently truncated. The UI stores/shows at most 8,000 characters of source excerpt.

Vision and enrichment use structured output with `store=False`. The provider's completion status is checked before the SDK parses structured text: an unfinished JSON object must not hide a content-filter stop or output limit. Filtered/refused responses, output limits, malformed results, and timeouts have distinct safe errors. Partial or refused results never reach Jev or the writer, and they are not automatically replayed. Document content is untrusted data and receives no tools. Raw documents, credentials, and upstream error bodies are not logged.

## State and proposals

SQLite contains jobs, cached inference, settings, sessions, tag definitions, intake fingerprints, and operation journals. Each proposal records its input fingerprint, taxonomy snapshot, before metadata, models, usage, latency, source, scores, and cache provenance. Reviewer approval and actual after metadata are distinct records within the job. The operation table stores write intent before network calls and confirmed results afterward.

Cache identity includes Paperless instance, document ID/text/checksum, eligible taxonomy and definitions, requested models, options, and prompt version. Approval checks use fresh Paperless state. Cached usage describes the original call; cache reuse makes no new inference call. Model scores are not measured accuracy.

Sessions contain only random opaque IDs in browser cookies, with hashes and CSRF tokens stored server-side. Password login verifies through Paperless and admits only the account whose API token matches this app's configured token. Direct token login is also supported. All mutations check both exact origin and CSRF (login checks origin); failed login attempts are rate limited per client address.

## Apply and recovery

Only reviewed jobs enter the writer. It re-fetches the document and taxonomy, checks text and label changes, and rejects conflicting title/type edits. Title and type are patched independently of tags. Tags use Paperless's additive bulk `modify_tags` operation with an empty removal set; asynchronous acceptance is followed by polling the actual document.

New tags are matched by normalized live name before creation. A timeout after creation can be reconciled by finding the name, without knowingly creating another tag. Multiple normalized matches require manual resolution. Document metadata operations similarly check whether the desired state already exists before retrying. Original files, OCR, correspondents, and existing tags are never replaced.

A restart turns interrupted inference into an explicit retry and interrupted application into an explicit reconciliation task. Reconciliation revalidates approved intent and current state. A failed proposal can be closed without undoing completed changes; this retains the journal and observed metadata, permitting a fresh classification. Late asynchronous additions can still finish. There is no transactional write across Paperless endpoints and no atomic compare-and-swap against another writer; avoid concurrent metadata automation for the same documents.

Intake is disabled by default. Enabled intake polls a selected tag once a minute, enqueues at most ten new documents per poll, and caps the processing backlog at 50. Removing the queue tag prevents later processing/application. The tag is retained after completion, and persisted input fingerprints prevent loops. A paused worker finishes its current operation but schedules/processes no new work.

## Deployment

The service runs on docker-server using Podman Quadlet, `services.network`, a Caddy hostname, and UID 10001 with a private local data volume. `home-ansible` owns infrastructure and secret-file permissions. Health checks only examine the database and worker; they never invoke a paid provider. See [operations](operations.md).
