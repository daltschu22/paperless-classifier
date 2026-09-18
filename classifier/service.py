import fcntl
import json
import logging
import threading
import time

from .config import AppError
from .contracts import Approval, Intake, Options, digest, metadata, tag_key, text_hash
from .providers import clean_suggestions

log = logging.getLogger("classifier")
CONTROL_TAGS = {"inbox", "needs-tags", "classifier", "classifier-queue"}


class Service:
    def __init__(self, settings, store, paperless, jev, generative):
        self.settings, self.store, self.paperless = settings, store, paperless
        self.jev, self.generative = jev, generative
        self.stop = threading.Event()
        self.thread = None
        self.document_titles = {}

    def jobs(self):
        jobs = self.store.jobs()
        visible = {job["document_id"] for job in jobs}
        for identifier in list(self.document_titles):
            if identifier not in visible:
                self.document_titles.pop(identifier, None)
        for job in jobs:
            title = (job.get("proposal") or {}).get("before", {}).get("title", "")
            if not title:
                identifier = job["document_id"]
                expires, title = self.document_titles.get(identifier, (0, ""))
                if expires <= time.monotonic():
                    try:
                        title = self.paperless.document(identifier).get("title", "")
                    except AppError:
                        pass  # Keep the last known name if Paperless is temporarily unavailable.
                    self.document_titles[identifier] = (time.monotonic() + 60, title)
            job["document_title"] = title
        return jobs

    def taxonomy(self):
        value = self.paperless.taxonomy()
        definitions = self.store.definitions()
        for tag in value["tags"]:
            tag["definition"] = definitions.get(tag["id"], "")
        return value

    def allowed(self, taxonomy):
        queue_id = self.store.setting("intake", {}).get("tag_id")
        return {"types": [{"id": t["id"], "name": t["name"]} for t in taxonomy["types"]],
                "tags": [{"id": t["id"], "name": t["name"], "definition": t.get("definition", "")} for t in taxonomy["tags"]
                    if not t.get("is_inbox_tag") and t["id"] != queue_id
                    and tag_key(t["name"]) not in CONTROL_TAGS and not tag_key(t["name"]).startswith("paperless-gpt")]}

    def process(self, job):
        document = self.paperless.document(job["document_id"])
        self.document_titles[job["document_id"]] = (time.monotonic() + 60, document.get("title", ""))
        queue_tag = job["options"].get("queue_tag_id")
        if queue_tag and queue_tag not in document.get("tags", []):
            raise AppError("queue_removed", "Document was removed from the intake queue.")
        options = Options.model_validate({k:v for k,v in job["options"].items() if k != "queue_tag_id"})
        taxonomy = self.allowed(self.taxonomy())
        text = document.get("content") or ""
        cache_key = digest({"instance": self.settings.paperless_url, "input": text_hash(document),
            "taxonomy": taxonomy, "options": options.model_dump(), "jev": self.settings.jev_model,
            "generative": self.settings.generative_model, "prompt": "hybrid-v3-readability"})
        analysis = self.store.cache_get(cache_key)
        cached = analysis is not None
        if analysis is None:
            source, usage = "paperless_ocr", []
            weak = len([c for c in text if c.isalnum()]) < 60 or text.count("\ufffd") > max(5, len(text) / 20)
            if options.force_vision or (weak and options.vision_fallback):
                data, mime = self.paperless.file(document["id"])
                vision, cost = self.generative.vision(data, mime)
                usage.append({"provider": "vision", **cost})
                if not vision["legible"] or not vision["text"].strip():
                    raise AppError("scan_unreadable", "The scan is not readable enough to classify. Review the original in Paperless.")
                text, source = vision["text"], "vision"
            if not text.strip():
                raise AppError("ocr_missing", "No OCR text is available. Retry with vision enabled.")
            if len(text) > self.settings.max_characters:
                raise AppError("input_too_large", "The document exceeds the 60,000-character processing limit.")
            enriched = {"title": "", "new_tags": []}
            if options.enrich:
                enriched, cost = self.generative.enrich(text, taxonomy)
                usage.append({"provider": "generative", **cost})
                if not enriched["text_readable"] and source == "paperless_ocr" and options.vision_fallback:
                    data, mime = self.paperless.file(document["id"])
                    vision, cost = self.generative.vision(data, mime)
                    usage.append({"provider": "vision", **cost})
                    if not vision["legible"] or not vision["text"].strip():
                        raise AppError("scan_unreadable", "The original scan is not readable enough to classify.")
                    text, source = vision["text"], "vision"
                    if len(text) > self.settings.max_characters:
                        raise AppError("input_too_large", "Vision text exceeds the processing limit.")
                    enriched, cost = self.generative.enrich(text, taxonomy)
                    usage.append({"provider": "generative", **cost})
                if not enriched["text_readable"]:
                    raise AppError("ocr_unreliable", "The document text is too garbled to classify. Read the original with vision or review it in Paperless.")
                enriched = clean_suggestions(enriched, taxonomy, text)
            answers, cost = self.jev.classify(text, taxonomy, enriched["new_tags"])
            usage.append({"provider": "jev", **cost})
            tag_matches = [{**tag, "probability": answers["tag_" + str(tag["id"])]["noul"]} for tag in taxonomy["tags"]]
            new_tags = [{**tag, "probability": answers["new_" + str(i)]["noul"]} for i, tag in enumerate(enriched["new_tags"])]
            chosen = answers.get("document_type")
            selected_type = None
            if chosen and chosen["choice"] != "unknown":
                selected_type = next(t for t in taxonomy["types"] if "type_" + str(t["id"]) == chosen["choice"])
            analysis = {"source": source, "excerpt": text[:8000], "excerpt_truncated": len(text) > 8000,
                "tags": sorted(tag_matches, key=lambda t: (-t["probability"], t["name"])),
                "new_tags": new_tags, "title": enriched["title"], "type": selected_type,
                "type_answer": chosen, "usage": usage}
            self.store.cache_set(cache_key, analysis)
        proposal = {**analysis, "document_id": document["id"], "before": metadata(document),
            "input_hash": text_hash(document), "taxonomy": taxonomy, "cache_key": cache_key, "cached": cached,
            "created_at": time.time(), "schema_version": 1}
        self.store.change(job["id"], ["running"], "review", proposal=proposal, error=None, error_code=None)

    def approve(self, identifier, approval):
        job = self.store.get(identifier)
        if not job or job["status"] not in ("review", "deferred"):
            raise AppError("state_conflict", "This proposal is no longer waiting for review.")
        if approval.title is not None and not approval.title.strip():
            raise AppError("empty_title", "A title cannot be empty.")
        taxonomy = self.allowed(self.taxonomy())
        if not set(approval.tag_ids) <= {t["id"] for t in taxonomy["tags"]}:
            raise AppError("invalid_tags", "A selected tag is missing or reserved for a workflow.")
        if approval.document_type is not None and approval.document_type not in {t["id"] for t in taxonomy["types"]}:
            raise AppError("invalid_type", "The selected document type no longer exists.")
        if any(i < 0 or i >= len(job["proposal"]["new_tags"]) for i in approval.new_tag_indices):
            raise AppError("invalid_new_tag", "A selected new tag is not part of this proposal.")
        if not self.store.change(identifier, ["review", "deferred"], "apply_queued", approval=approval.model_dump(), error=None, error_code=None):
            raise AppError("state_conflict", "This proposal has already been handled.")

    def apply(self, job):
        proposal = job["proposal"]
        approval = Approval.model_validate(job["approval"])
        doc_id = job["document_id"]
        current = self.paperless.document(doc_id)
        if text_hash(current) != proposal["input_hash"]:
            raise AppError("stale_document", "Document text changed after classification. Reclassify before applying.")
        queue_id = job["options"].get("queue_tag_id")
        if queue_id and queue_id not in current.get("tags", []):
            raise AppError("queue_removed", "Document was removed from the intake queue.")
        taxonomy = self.taxonomy()
        # New entries are allowed; renaming/deleting entries used during inference is not.
        for group in ("tags", "types"):
            live = {t["id"]: t["name"] for t in taxonomy[group]}
            if any(live.get(t["id"]) != t["name"] for t in proposal["taxonomy"][group]):
                raise AppError("stale_taxonomy", "The taxonomy changed. Reclassify before applying.")
        definitions = {t["id"]: t.get("definition", "") for t in taxonomy["tags"]}
        if any(definitions[t["id"]] != t.get("definition", "") for t in proposal["taxonomy"]["tags"]):
            raise AppError("stale_taxonomy", "Tag definitions changed. Reclassify before applying.")
        allowed = self.allowed(taxonomy)
        if not set(approval.tag_ids) <= {t["id"] for t in allowed["tags"]}:
            raise AppError("stale_tags", "A selected tag is no longer available for classification.")
        if approval.document_type is not None and approval.document_type not in {t["id"] for t in allowed["types"]}:
            raise AppError("stale_type", "The selected document type no longer exists.")
        values = {}
        if approval.title is not None:
            values["title"] = approval.title.strip()
            if not values["title"]:
                raise AppError("empty_title", "A title cannot be empty.")
        if approval.document_type is not None:
            values["document_type"] = approval.document_type
        for field, desired in values.items():
            if current.get(field) not in (proposal["before"].get(field), desired):
                raise AppError("stale_metadata", "Someone changed the title or type after classification. Reclassify before applying.")

        ids = set(approval.tag_ids)
        for index in sorted(set(approval.new_tag_indices)):
            proposed = proposal["new_tags"][index]
            name = "tag:" + str(index)
            self.store.operation(job["id"], name, {"name": proposed["name"], "definition": proposed["definition"]})
            matches = [t for t in self.paperless.all("tags") if tag_key(t["name"]) == tag_key(proposed["name"])]
            if len(matches) > 1:
                raise AppError("duplicate_tag", "Several existing tags have the proposed name. Resolve the duplicate in Paperless.")
            if matches:
                created = matches[0]
                if (created.get("is_inbox_tag") or tag_key(created["name"]) in CONTROL_TAGS
                        or tag_key(created["name"]).startswith("paperless-gpt")
                        or created["id"] == self.store.setting("intake", {}).get("tag_id")):
                    raise AppError("reserved_tag", "A new tag conflicts with an operational tag.")
            else:
                # On timeout the next reconciliation finds the tag by normalized name.
                created = self.paperless.create_tag(proposed["name"])
            ids.add(created["id"])
            self.store.define(created["id"], proposed["definition"])
            self.store.finish_operation(job["id"], name, {"tag_id": created["id"]})

        # Field-specific updates never send tags or unrelated document metadata.
        if values:
            self.store.operation(job["id"], "metadata", {"before": proposal["before"], "desired": values})
            current = self.paperless.document(doc_id)
            if text_hash(current) != proposal["input_hash"]:
                raise AppError("stale_document", "Document text changed before the update.")
            for field, desired in values.items():
                if current.get(field) not in (proposal["before"].get(field), desired):
                    raise AppError("stale_metadata", "The document changed before the update.")
            pending = {k:v for k,v in values.items() if current.get(k) != v}
            if pending:
                self.paperless.patch(doc_id, pending)
            current = self.paperless.document(doc_id)
            if any(current.get(k) != v for k,v in values.items()):
                raise AppError("write_unconfirmed", "Paperless has not confirmed the metadata changes. Reconcile to check again.")
            self.store.finish_operation(job["id"], "metadata", metadata(current))
        if ids:
            operation = self.store.operation(job["id"], "tags", {"add": sorted(ids), "before": current.get("tags", [])})
            current = self.paperless.document(doc_id)
            if text_hash(current) != proposal["input_hash"]:
                raise AppError("stale_document", "Document text changed before tag application.")
            missing = ids - set(current.get("tags", []))
            if missing:
                # Adding a set twice is idempotent even if an earlier asynchronous task finishes late.
                result = self.paperless.add_tags(doc_id, missing)
                self.store.finish_operation(job["id"], "tags", {"task": result}, complete=False)
                for _ in range(30):
                    current = self.paperless.document(doc_id)
                    if ids <= set(current.get("tags", [])):
                        break
                    if self.stop.wait(1):
                        raise AppError("interrupted", "Apply was interrupted. Reconcile the outcome.")
                else:
                    raise AppError("tags_pending", "Tag changes are still pending in Paperless. Reconcile to verify completion.")
            self.store.finish_operation(job["id"], "tags", {"added": sorted(ids - set(operation["payload"]["before"])), "after": current.get("tags", [])})
        final = self.paperless.document(doc_id)
        if not ids <= set(final.get("tags", [])) or any(final.get(k) != v for k,v in values.items()):
            raise AppError("write_conflict", "Metadata changed during application. Review the document and reconcile.")
        self.store.change(job["id"], ["applying"], "applied", proposal={**proposal, "after": metadata(final)}, error=None, error_code=None)
        self.store.seen(doc_id, text_hash(final))

    def step(self):
        job = self.store.claim()
        if not job:
            return False
        try:
            if job["status"] == "running":
                self.process(job)
            else:
                self.apply(job)
        except AppError as error:
            self.store.change(job["id"], [job["status"]], "error" if job["status"] == "running" else "apply_error", error=error.message, error_code=error.code)
            log.warning("Job %s: %s", job["id"], error.code)
        except Exception as error:
            self.store.change(job["id"], [job["status"]], "error" if job["status"] == "running" else "apply_error", error="Processing failed. Check service health and retry.", error_code="internal_error")
            log.error("Job %s failed: %s", job["id"], type(error).__name__)
        return True

    def poll(self):
        intake = Intake.model_validate(self.store.setting("intake", {}))
        if not intake.enabled or not intake.tag_id or self.store.setting("paused", False):
            return
        scheduled = 0
        for page in range(1, 101):
            documents = self.paperless.documents(page=page, tag_id=intake.tag_id)
            for doc in documents["results"]:
                if self.store.pending_count() >= 50:
                    return
                fingerprint = text_hash(doc)
                if self.store.seen(doc["id"]) == fingerprint:
                    continue
                _, added = self.store.enqueue(doc["id"], {"enrich": intake.enrich, "vision_fallback": intake.vision_fallback, "force_vision": False, "queue_tag_id": intake.tag_id})
                self.store.seen(doc["id"], fingerprint)
                scheduled += added
                if scheduled >= 10:
                    return
            if not documents.get("next"):
                return

    def start(self):
        self.lock = open(self.store.directory / "worker.lock", "a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another classifier worker owns this data directory.") from None
        self.store.recover()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        last_poll = 0
        while not self.stop.is_set():
            if time.monotonic() - last_poll >= 60:
                try:
                    self.poll()
                    self.store.set_setting("intake_error", None)
                except Exception:
                    self.store.set_setting("intake_error", "Queue polling failed. Check the Paperless connection and selected tag.")
                last_poll = time.monotonic()
            if not self.store.setting("paused", False) and self.step():
                continue
            self.stop.wait(1)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        # OS releases the lock at process exit if a network call is still finishing.
        if not self.thread or not self.thread.is_alive():
            self.lock.close()
