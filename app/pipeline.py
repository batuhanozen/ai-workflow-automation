import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.logging import configure_logging
from app.models import AIResult, ProcessingError, SupportRequest
from app.providers.base import AIProvider, ProviderError
from app.rules import BusinessRuleError, validate_business_rules
from app.schemas import Category, Classification, Priority

logger = configure_logging()


@dataclass
class AttemptError:
    attempt: int
    code: str
    message: str
    retryable: bool = False
    details: list[dict] = field(default_factory=list)


@dataclass
class Outcome:
    classification: Classification
    is_fallback: bool
    attempts: int
    duration_ms: int
    schema_valid: bool
    errors: list[AttemptError]


def fallback(description: str) -> Classification:
    return Classification(
        category=Category.GENERAL,
        priority=Priority.MEDIUM,
        summary="Automated classification unavailable; manual triage required.",
        suggested_action="Review the original request and assess its actual urgency manually.",
        confidence=0.0,
        evidence=description[:600],
        impact="routine",
    )


class Pipeline:
    def __init__(
        self, provider: AIProvider, settings: Settings, sleep: Callable[[float], None] = time.sleep
    ):
        self.provider, self.settings, self.sleep = provider, settings, sleep

    def run(
        self, title: str, description: str, on_error: Callable[[AttemptError], None] | None = None
    ) -> Outcome:
        started = time.monotonic()
        errors: list[AttemptError] = []
        schema_valid = False
        for attempt in range(1, self.settings.llm_max_attempts + 1):
            try:
                raw = self.provider.classify(title, description)
                result = Classification.model_validate_json(raw)
                schema_valid = True
                validate_business_rules(result, title, description)
                return Outcome(
                    result, False, attempt, int((time.monotonic() - started) * 1000), True, errors
                )
            except ProviderError as exc:
                error = AttemptError(attempt, exc.code, exc.safe_message, exc.retryable)
            except ValidationError as exc:
                # Never persist raw model output or echoed input from validation errors.
                details = [
                    {"field": ".".join(map(str, e["loc"])), "type": e["type"]}
                    for e in exc.errors(include_input=False, include_context=False)
                ]
                error = AttemptError(
                    attempt,
                    "schema_validation",
                    "AI output failed schema validation",
                    details=details,
                )
            except BusinessRuleError:
                error = AttemptError(
                    attempt, "business_rule", "AI output failed evidence or priority rules"
                )
            except Exception:
                # Custom adapter defects must fail visibly without leaking exception text.
                error = AttemptError(attempt, "internal_provider", "Unexpected AI provider failure")
            errors.append(error)
            if on_error:
                on_error(error)
            if not error.retryable or attempt == self.settings.llm_max_attempts:
                break
            self.sleep(self.settings.llm_backoff_seconds * (2 ** (attempt - 1)))
        return Outcome(
            fallback(description),
            True,
            attempt,
            int((time.monotonic() - started) * 1000),
            schema_valid,
            errors,
        )


class Processor:
    def __init__(self, sessions: sessionmaker[Session], pipeline: Pipeline):
        self.sessions, self.pipeline = sessions, pipeline

    def process(self, request_id: str) -> bool:
        with self.sessions.begin() as db:
            claimed = db.execute(
                update(SupportRequest)
                .where(
                    SupportRequest.id == request_id,
                    SupportRequest.status == "pending",
                )
                .values(status="processing", version=SupportRequest.version + 1)
            )
            if claimed.rowcount != 1:
                return False
            request = db.get(SupportRequest, request_id)
            title, description = request.title, request.description
        logger.info("processing_started", extra={"request_id": request_id})

        def record_error(error: AttemptError) -> None:
            with self.sessions.begin() as db:
                db.add(ProcessingError(request_id=request_id, **vars(error)))
            logger.warning(
                "processing_attempt_failed",
                extra={
                    "request_id": request_id,
                    "code": error.code,
                    "attempt": error.attempt,
                },
            )

        outcome = self.pipeline.run(title, description, record_error)
        with self.sessions.begin() as db:
            request = db.get(SupportRequest, request_id)
            request.status = "failed" if outcome.is_fallback else "completed"
            request.category = outcome.classification.category.value
            request.priority = outcome.classification.priority.value
            request.version += 1
            db.add(
                AIResult(
                    request_id=request_id,
                    provider=self.pipeline.provider.name,
                    model=self.pipeline.provider.model,
                    classification=outcome.classification.model_dump(mode="json"),
                    is_fallback=outcome.is_fallback,
                    attempts=outcome.attempts,
                    duration_ms=outcome.duration_ms,
                )
            )
        logger.info(
            "processing_failed" if outcome.is_fallback else "processing_completed",
            extra={"request_id": request_id},
        )
        return True

    def recover_interrupted(self) -> int:
        """Single-process startup recovery. Never disguise interrupted work as a success."""
        with self.sessions.begin() as db:
            requests = db.scalars(
                select(SupportRequest).where(SupportRequest.status.in_(["pending", "processing"]))
            ).all()
            for request in requests:
                result = fallback(request.description)
                request.status = "failed"
                request.category, request.priority = result.category.value, result.priority.value
                request.version += 1
                db.add(
                    ProcessingError(
                        request_id=request.id,
                        attempt=0,
                        code="interrupted",
                        message="Processing interrupted by restart; retry or review required",
                    )
                )
                db.add(
                    AIResult(
                        request_id=request.id,
                        provider=self.pipeline.provider.name,
                        model=self.pipeline.provider.model,
                        classification=result.model_dump(mode="json"),
                        is_fallback=True,
                        attempts=0,
                        duration_ms=0,
                    )
                )
            return len(requests)
