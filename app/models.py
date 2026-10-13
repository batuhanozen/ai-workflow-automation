from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def now() -> datetime:
    return datetime.now(UTC)


class SupportRequest(Base):
    __tablename__ = "requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Materialized effective values enable filtering without altering AI history.
    category: Mapped[str | None] = mapped_column(String(40), index=True)
    priority: Mapped[str | None] = mapped_column(String(20), index=True)
    results: Mapped[list["AIResult"]] = relationship(
        back_populates="request", order_by="AIResult.id", cascade="all, delete-orphan"
    )
    errors: Mapped[list["ProcessingError"]] = relationship(
        order_by="ProcessingError.id", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["Review"]] = relationship(
        order_by="Review.id", cascade="all, delete-orphan"
    )


class AIResult(Base):
    __tablename__ = "ai_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(30), default="triage-v1")
    classification: Mapped[dict] = mapped_column(JSON)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    request: Mapped[SupportRequest] = relationship(back_populates="results")


class ProcessingError(Base):
    __tablename__ = "processing_errors"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    attempt: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(String(250))
    details: Mapped[list] = mapped_column(JSON, default=list)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("ai_results.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    reviewer: Mapped[str] = mapped_column(String(80))
    note: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40))
    priority: Mapped[str] = mapped_column(String(20))
    suggested_action: Mapped[str] = mapped_column(String(600))
    action_approved: Mapped[bool] = mapped_column(Boolean)
