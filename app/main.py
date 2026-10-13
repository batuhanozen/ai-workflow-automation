import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.db import Base, build_database
from app.logging import configure_logging
from app.models import AIResult, ProcessingError, Review, SupportRequest
from app.pipeline import Pipeline, Processor
from app.providers.base import AIProvider
from app.providers.mock import MockProvider
from app.providers.openai import OpenAIProvider
from app.schemas import (
    ActivityRead,
    Category,
    Priority,
    RequestCreate,
    RequestDetail,
    RequestPage,
    ReviewCreate,
    StatsRead,
    Status,
)

STATIC = Path(__file__).parent / "static"
logger = configure_logging()


def iso(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat()


def serialize_result(result: AIResult) -> dict:
    return {
        "id": result.id,
        "created_at": iso(result.created_at),
        "provider": result.provider,
        "model": result.model,
        "prompt_version": result.prompt_version,
        "classification": result.classification,
        "is_fallback": result.is_fallback,
        "attempts": result.attempts,
        "duration_ms": result.duration_ms,
    }


def serialize(request: SupportRequest, detail: bool = False) -> dict:
    latest = request.results[-1] if request.results else None
    review = request.reviews[-1] if request.reviews else None
    effective = dict(latest.classification) if latest else None
    if effective and review:
        effective.update(
            category=review.category,
            priority=review.priority,
            suggested_action=review.suggested_action,
        )
    result = {
        "id": request.id,
        "title": request.title,
        "created_at": iso(request.created_at),
        "updated_at": iso(request.updated_at),
        "status": request.status,
        "version": request.version,
        "reviewed": request.reviewed,
        "classification": effective,
        "action_approved": review.action_approved if review else False,
        "is_fallback": latest.is_fallback if latest else False,
        "provider": latest.provider if latest else None,
    }
    if detail:
        result.update(
            description=request.description,
            results=[serialize_result(r) for r in request.results],
            errors=[
                {
                    "id": e.id,
                    "created_at": iso(e.created_at),
                    "attempt": e.attempt,
                    "code": e.code,
                    "message": e.message,
                    "details": e.details,
                    "retryable": e.retryable,
                }
                for e in request.errors
            ],
            reviews=[
                {
                    "id": r.id,
                    "result_id": r.result_id,
                    "created_at": iso(r.created_at),
                    "reviewer": r.reviewer,
                    "note": r.note,
                    "category": r.category,
                    "priority": r.priority,
                    "suggested_action": r.suggested_action,
                    "action_approved": r.action_approved,
                }
                for r in request.reviews
            ],
        )
    return result


def create_app(settings: Settings | None = None, provider: AIProvider | None = None) -> FastAPI:
    settings = settings or Settings()
    engine, sessions = build_database(settings.database_url)
    provider = provider or (
        MockProvider() if settings.ai_provider == "mock" else OpenAIProvider(settings)
    )
    processor = Processor(sessions, Pipeline(provider, settings))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        Base.metadata.create_all(engine)
        processor.recover_interrupted()
        yield
        engine.dispose()

    app = FastAPI(title="AI Workflow Automation", version="0.1.0", lifespan=lifespan)
    app.state.sessions, app.state.processor, app.state.settings = sessions, processor, settings

    def get_db():
        with sessions() as db:
            yield db

    def authenticate(x_api_key: Annotated[str | None, Header()] = None) -> None:
        expected = settings.api_key.get_secret_value()
        if expected and not secrets.compare_digest(
            (x_api_key or "").encode("utf-8"), expected.encode("utf-8")
        ):
            raise HTTPException(401, "A valid X-API-Key header is required")

    DB = Annotated[Session, Depends(get_db)]
    api = APIRouter(prefix="/api", dependencies=[Depends(authenticate)])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # Enforce an actual streaming byte limit, not only Content-Length.
        if request.method in {"POST", "PUT", "PATCH"}:
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 65536:
                    return JSONResponse({"detail": "Request body exceeds 64 KiB"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        # Swagger uses its own CDN scripts; the dashboard has no external assets or inline scripts.
        if not request.url.path.startswith(("/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Input validation failed",
                "errors": [
                    {
                        "field": "unknown"
                        if e["type"] == "extra_forbidden"
                        else ".".join(map(str, e["loc"])),
                        "type": e["type"],
                    }
                    for e in exc.errors()
                ],
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, _exc: Exception):
        logger.error("unhandled_api_error")
        return JSONResponse(status_code=500, content={"detail": "Internal error; please try again"})

    @app.get("/health", tags=["operations"])
    def health(db: DB):
        db.execute(select(1))
        return {"status": "ok"}

    @api.get("/config")
    def config():
        return {
            "provider": provider.name,
            "model": provider.model,
            "categories": list(Category),
            "priorities": list(Priority),
        }

    @api.post("/requests", status_code=201, response_model=RequestDetail)
    def create_request(payload: RequestCreate, background: BackgroundTasks, db: DB):
        request = SupportRequest(**payload.model_dump())
        db.add(request)
        db.commit()
        db.refresh(request)
        result = serialize(request, detail=True)
        background.add_task(processor.process, request.id)
        return result

    @api.get("/requests", response_model=RequestPage)
    def list_requests(
        db: DB,
        status: Status | None = None,
        category: Category | None = None,
        priority: Priority | None = None,
        reviewed: bool | None = None,
        needs_review: bool = False,
        q: str = Query(default="", max_length=160),
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        query = select(SupportRequest)
        if needs_review:
            query = query.where(
                SupportRequest.reviewed.is_(False),
                SupportRequest.status.in_(["completed", "failed"]),
            )
        for column, value in [
            (SupportRequest.status, status),
            (SupportRequest.category, category),
            (SupportRequest.priority, priority),
            (SupportRequest.reviewed, reviewed),
        ]:
            if value is not None:
                query = query.where(column == value)
        if q:
            query = query.where(SupportRequest.title.contains(q, autoescape=True))
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        items = db.scalars(
            query.options(
                selectinload(SupportRequest.results), selectinload(SupportRequest.reviews)
            )
            .order_by(SupportRequest.created_at.desc(), SupportRequest.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return {
            "items": [serialize(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def find_request(db: Session, request_id: UUID) -> SupportRequest:
        request = db.get(SupportRequest, str(request_id))
        if not request:
            raise HTTPException(404, "Request not found")
        return request

    @api.get("/requests/{request_id}", response_model=RequestDetail)
    def detail(request_id: UUID, db: DB):
        return serialize(find_request(db, request_id), detail=True)

    @api.post("/requests/{request_id}/retry", status_code=202)
    def retry(request_id: UUID, background: BackgroundTasks, db: DB):
        find_request(db, request_id)
        changed = db.execute(
            update(SupportRequest)
            .where(
                SupportRequest.id == str(request_id),
                SupportRequest.status == "failed",
                SupportRequest.reviewed.is_(False),
            )
            .values(status="pending", version=SupportRequest.version + 1)
        )
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "Only failed, unreviewed requests can be retried")
        db.commit()
        background.add_task(processor.process, str(request_id))
        return {"id": str(request_id), "status": "pending"}

    @api.post("/requests/{request_id}/reviews", status_code=201, response_model=RequestDetail)
    def review(request_id: UUID, payload: ReviewCreate, db: DB):
        request = find_request(db, request_id)
        if request.status not in ("completed", "failed") or not request.results:
            raise HTTPException(409, "Wait for processing to finish before reviewing")
        changed = db.execute(
            update(SupportRequest)
            .where(
                SupportRequest.id == str(request_id),
                SupportRequest.version == payload.expected_version,
                SupportRequest.status.in_(["completed", "failed"]),
            )
            .values(
                reviewed=True,
                category=payload.category.value,
                priority=payload.priority.value,
                version=SupportRequest.version + 1,
            )
        )
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "Request changed; reload before saving your review")
        db.add(
            Review(
                request_id=str(request_id),
                result_id=request.results[-1].id,
                **payload.model_dump(exclude={"expected_version"}),
            )
        )
        db.commit()
        db.expire_all()
        return serialize(find_request(db, request_id), detail=True)

    @api.get("/stats", response_model=StatsRead)
    def stats(db: DB):
        statuses = dict(
            db.execute(
                select(SupportRequest.status, func.count()).group_by(SupportRequest.status)
            ).all()
        )

        def counts(column):
            return dict(
                db.execute(
                    select(column, func.count()).where(column.is_not(None)).group_by(column)
                ).all()
            )

        needs_review = db.scalar(
            select(func.count())
            .select_from(SupportRequest)
            .where(
                SupportRequest.reviewed.is_(False),
                SupportRequest.status.in_(["completed", "failed"]),
            )
        )
        return {
            "total": sum(statuses.values()),
            "processed": statuses.get("completed", 0),
            "failed": statuses.get("failed", 0),
            "pending": statuses.get("pending", 0) + statuses.get("processing", 0),
            "needs_review": needs_review,
            "by_category": counts(SupportRequest.category),
            "by_priority": counts(SupportRequest.priority),
        }

    @api.get("/activity", response_model=list[ActivityRead])
    def activity(db: DB):
        events: list[dict[str, str]] = []
        # Each source is bounded before merging, keeping the feed query small.
        for model, label in [
            (AIResult, "Classification recorded"),
            (Review, "Human review saved"),
            (ProcessingError, "Processing error recorded"),
        ]:
            rows = db.execute(
                select(model, SupportRequest.title)
                .join(SupportRequest, model.request_id == SupportRequest.id)
                .order_by(model.created_at.desc(), model.id.desc())
                .limit(6)
            ).all()
            for entry, title in rows:
                event = label
                if isinstance(entry, AIResult) and entry.is_fallback:
                    event = "Fallback recorded · manual triage required"
                events.append(
                    {
                        "request_id": entry.request_id,
                        "title": title,
                        "created_at": iso(entry.created_at),
                        "event": event,
                    }
                )
        return sorted(events, key=lambda event: event["created_at"], reverse=True)[:6]

    app.include_router(api)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(STATIC / "index.html")

    return app
