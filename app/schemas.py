from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Category(StrEnum):
    IT = "IT Support"
    SOFTWARE = "Software Issue"
    ACCOUNT = "Account Access"
    INFRASTRUCTURE = "Infrastructure"
    SECURITY = "Security"
    GENERAL = "General Request"


class Priority(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class Status(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RequestCreate(StrictModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=10000)


class Classification(StrictModel):
    category: Category
    priority: Priority
    summary: str = Field(min_length=5, max_length=400)
    suggested_action: str = Field(min_length=5, max_length=600)
    confidence: float = Field(ge=0, le=1, strict=True, allow_inf_nan=False)
    evidence: str = Field(min_length=8, max_length=600)
    impact: Literal["routine", "individual_blocked", "widespread_outage", "security_incident"]

    @field_validator("summary", "suggested_action", "evidence", mode="before")
    @classmethod
    def strings_only(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("Expected a string")
        return value


class ReviewCreate(StrictModel):
    category: Category
    priority: Priority
    suggested_action: str = Field(min_length=5, max_length=600)
    action_approved: bool = Field(strict=True)
    reviewer: str = Field(min_length=2, max_length=80)
    note: str = Field(min_length=5, max_length=1000)
    expected_version: int = Field(ge=1, strict=True)


class ResultRead(StrictModel):
    id: int
    created_at: str
    provider: str
    model: str
    prompt_version: str
    classification: Classification
    is_fallback: bool
    attempts: int
    duration_ms: int


class ErrorRead(StrictModel):
    id: int
    created_at: str
    attempt: int
    code: str
    message: str
    details: list[dict[str, str]]
    retryable: bool


class ReviewRead(StrictModel):
    id: int
    result_id: int
    created_at: str
    reviewer: str
    note: str
    category: Category
    priority: Priority
    suggested_action: str
    action_approved: bool


class RequestRead(StrictModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    status: Status
    version: int
    reviewed: bool
    classification: Classification | None
    action_approved: bool
    is_fallback: bool
    provider: str | None


class RequestDetail(RequestRead):
    description: str
    results: list[ResultRead]
    errors: list[ErrorRead]
    reviews: list[ReviewRead]


class RequestPage(StrictModel):
    items: list[RequestRead]
    total: int
    limit: int
    offset: int


class StatsRead(StrictModel):
    total: int
    processed: int
    failed: int
    pending: int
    needs_review: int
    by_category: dict[Category, int]
    by_priority: dict[Priority, int]


class ActivityRead(StrictModel):
    request_id: str
    title: str
    created_at: str
    event: str
