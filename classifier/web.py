from collections import defaultdict
from contextlib import asynccontextmanager
import hmac
from pathlib import Path
import threading
import time

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .config import AppError, Settings
from .contracts import Approval, Intake, Options, QueueRequest, metadata, tag_key
from .paperless import Paperless
from .providers import Generative, Jev
from .service import Service
from .store import Store

ROOT = Path(__file__).resolve().parent


class Login(BaseModel):
    username: str = Field(default="", max_length=150)
    password: str = Field(default="", max_length=1024)
    token: str = Field(default="", max_length=512)


class Definition(BaseModel):
    definition: str = Field(max_length=500)


def create_app(settings=None, service=None, worker_enabled=True):
    if settings is None:
        load_dotenv()
        settings = Settings.from_env()
    if service is None:
        service = Service(settings, Store(settings.data_dir), Paperless(settings), Jev(settings), Generative(settings))
    store = service.store

    @asynccontextmanager
    async def lifespan(app):
        if worker_enabled:
            service.start()
        yield
        if worker_enabled:
            service.close()

    app = FastAPI(title="Paperless Classifier", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service
    templates = Jinja2Templates(directory=ROOT / "templates")
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    login_attempts = defaultdict(list)
    login_lock = threading.Lock()

    @app.exception_handler(AppError)
    async def app_error(request, error):
        return JSONResponse({"error": error.message, "code": error.code}, status_code=400)

    @app.middleware("http")
    async def security(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("origin") != settings.origin:
                return JSONResponse({"error": "Unexpected request origin."}, status_code=403)
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"error": "Invalid request length."}, status_code=400)
            if length > 65536:
                return JSONResponse({"error": "Request is too large."}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    def authenticated(request: Request):
        csrf = store.authenticated(request.cookies.get("classifier_session", ""))
        if not csrf:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Sign in to continue.")
        if request.method != "GET" and not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Refresh the page and try again.")
        return csrf

    @app.get("/healthz")
    def health():
        store.setting("paused", False)
        ready = not worker_enabled or (service.thread is not None and service.thread.is_alive())
        return JSONResponse({"status": "ok" if ready else "starting"}, status_code=200 if ready else 503)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        csrf = store.authenticated(request.cookies.get("classifier_session", ""))
        if not csrf:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(request=request, name="app.html", context={"csrf": csrf})

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        return templates.TemplateResponse(request=request, name="login.html", context={})

    @app.post("/api/login")
    def login(body: Login, request: Request):
        address = request.client.host if request.client else "local"
        with login_lock:
            now = time.time()
            login_attempts[address] = [t for t in login_attempts[address] if t > now-300]
            if len(login_attempts[address]) >= 10:
                return JSONResponse({"error": "Too many attempts. Try again in five minutes."}, status_code=429)
            login_attempts[address].append(now)
        token = body.token or service.paperless.login(body.username, body.password)
        if not token or not hmac.compare_digest(token, settings.paperless_token):
            return JSONResponse({"error": "Use the Paperless account connected to this classifier, or its API token."}, status_code=401)
        # The service token identifies the single allowed Paperless account.
        # Login never creates a session for another account with a narrower document view.
        session = store.session()
        response = JSONResponse({"ok": True})
        response.set_cookie("classifier_session", session, httponly=True, secure=settings.origin.startswith("https://"), samesite="strict", max_age=43200)
        return response

    @app.post("/api/logout", dependencies=[Depends(authenticated)])
    def logout(request: Request):
        store.logout(request.cookies.get("classifier_session", ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie("classifier_session")
        return response

    @app.get("/api/state", dependencies=[Depends(authenticated)])
    def state():
        jobs = service.jobs()
        return {"jobs": jobs, "paused": store.setting("paused", False),
                "intake": store.setting("intake", Intake().model_dump()), "intake_error": store.setting("intake_error"),
                "generative_ready": bool(settings.openai_key), "paperless_url": settings.paperless_public_url or settings.paperless_url}

    @app.get("/api/taxonomy", dependencies=[Depends(authenticated)])
    def taxonomy():
        return service.taxonomy()

    @app.get("/api/documents", dependencies=[Depends(authenticated)])
    def documents(page: int = 1, query: str = ""):
        if page < 1 or len(query) > 300:
            raise AppError("invalid_search", "Invalid document search.")
        result = service.paperless.documents(page, query)
        # OCR is loaded only for processing or document review.
        return {"count": result["count"], "next": bool(result.get("next")),
                "results": [{k:d.get(k) for k in ("id", "title", "tags", "document_type", "added")} for d in result["results"]]}

    @app.post("/api/jobs", dependencies=[Depends(authenticated)])
    def queue(body: QueueRequest):
        if any(doc_id <= 0 for doc_id in body.document_ids):
            raise AppError("invalid_id", "Document IDs must be positive.")
        pending = store.pending_count()
        if pending + len(set(body.document_ids)) > 50:
            raise AppError("queue_full", "The queue is full. Let current jobs finish before adding more.")
        options = Options.model_validate(body.model_dump(exclude={"document_ids"})).model_dump()
        return {"jobs": [store.enqueue(doc_id, options)[0] for doc_id in sorted(set(body.document_ids))]}

    @app.post("/api/jobs/{identifier}/apply", dependencies=[Depends(authenticated)])
    def apply(identifier: str, body: Approval):
        service.approve(identifier, body)
        return {"ok": True}

    @app.post("/api/jobs/{identifier}/{action}", dependencies=[Depends(authenticated)])
    def action(identifier: str, action: str, body: Options | None = None):
        job = store.get(identifier)
        if not job:
            raise AppError("missing_job", "This proposal no longer exists.")
        if action in ("defer", "reject", "restore"):
            expected = {"defer": ["review", "deferred"], "reject": ["review", "deferred", "error"], "restore": ["deferred"]}[action]
            status = {"defer": "deferred", "reject": "rejected", "restore": "review"}[action]
            success = store.change(identifier, expected, status)
        elif action == "retry":
            options = {**job["options"], **(body.model_dump(exclude_unset=True) if body else {})}
            if job["options"].get("queue_tag_id"):
                options["queue_tag_id"] = job["options"]["queue_tag_id"]
            success = store.change(identifier, ["error", "review", "deferred"], "queued", options=options, error=None, error_code=None)
        elif action == "reconcile":
            success = store.change(identifier, ["apply_error"], "apply_queued", error=None, error_code=None)
        elif action == "abandon":
            # Preserve the approval, operation journal and observed metadata. This is not undo.
            observed = metadata(service.paperless.document(job["document_id"]))
            success = store.change(identifier, ["apply_error"], "abandoned",
                proposal={**job["proposal"], "observed_after_error": observed})
        else:
            raise AppError("invalid_action", "Unknown action.")
        if not success:
            raise AppError("state_conflict", "This job has changed. Refresh before continuing.")
        return {"ok": True}

    @app.post("/api/pause", dependencies=[Depends(authenticated)])
    def pause():
        store.set_setting("paused", not store.setting("paused", False))
        return {"paused": store.setting("paused")}

    @app.post("/api/intake", dependencies=[Depends(authenticated)])
    def intake(body: Intake):
        if body.enabled and body.tag_id not in {t["id"] for t in service.paperless.all("tags")}:
            raise AppError("invalid_queue", "Choose an existing intake tag.")
        store.set_setting("intake", body.model_dump())
        return {"ok": True}

    @app.post("/api/intake/create-tag", dependencies=[Depends(authenticated)])
    def create_intake_tag():
        existing = [t for t in service.paperless.all("tags") if tag_key(t["name"]) == "classifier-queue"]
        tag = existing[0] if existing else service.paperless.create_tag("classifier-queue")
        intake = store.setting("intake", Intake().model_dump())
        intake["tag_id"] = tag["id"]
        store.set_setting("intake", intake)
        return {"id": tag["id"]}

    @app.post("/api/tags/{tag_id}/definition", dependencies=[Depends(authenticated)])
    def definition(tag_id: int, body: Definition):
        if tag_id not in {t["id"] for t in service.paperless.all("tags")}:
            raise AppError("missing_tag", "This tag no longer exists.")
        store.define(tag_id, body.definition.strip())
        return {"ok": True}

    return app
