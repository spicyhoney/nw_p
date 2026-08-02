from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

CaseStatus = Literal["pending_provider", "accepted", "rejected"]
ProviderDecision = Literal["accept", "reject"]
ContactAccess = Literal["masked", "full", "unavailable"]
AnswerValue = str | list[str]
AuditEventType = Literal[
    "case_submitted",
    "provider_accepted",
    "provider_rejected",
    "contact_revealed",
]
TAIPEI_UTC_OFFSET = timedelta(hours=8)
MAX_CASE_TIME_WINDOW = timedelta(hours=12)


def validate_case_time_window(
    *,
    preferred_start: datetime,
    preferred_end: datetime,
) -> None:
    if (
        preferred_start.tzinfo is None
        or preferred_start.utcoffset() != TAIPEI_UTC_OFFSET
        or preferred_end.tzinfo is None
        or preferred_end.utcoffset() != TAIPEI_UTC_OFFSET
    ):
        raise ValueError("case time window must use Asia/Taipei +08:00")
    if preferred_end <= preferred_start:
        raise ValueError("case time window must end after it starts")
    if preferred_end - preferred_start > MAX_CASE_TIME_WINDOW:
        raise ValueError("case time window must not exceed 12 hours")


class CaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_server_relative_image_path(image_path: str | None) -> str | None:
    if image_path is None:
        return None
    normalized = image_path.strip()
    segments = normalized.split("/")
    if (
        not normalized
        or normalized.startswith("/")
        or "\\" in normalized
        or (len(normalized) >= 2 and normalized[0].isalpha() and normalized[1] == ":")
        or any(segment in {"", ".", ".."} for segment in segments)
    ):
        raise ValueError("image_path must be a non-empty server-relative path without traversal")
    return normalized


class SyntheticContact(CaseModel):
    name: str = Field(min_length=1, max_length=80)
    mobile: str = Field(min_length=1, max_length=30)
    address: str = Field(min_length=1, max_length=200)
    source_type: Literal["synthetic"] = "synthetic"


class CaseImageAnalysis(CaseModel):
    """Structured, persisted result of analysis for an optional case image."""

    service_query: str = Field(min_length=1, max_length=500)
    problem_summary: str = Field(min_length=1, max_length=1000)
    safety_warnings: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0, le=1)
    uncertain: bool
    confirmed: bool
    correction: str | None = Field(default=None, min_length=1, max_length=1000)

    @field_validator("safety_warnings")
    @classmethod
    def validate_safety_warnings(cls, warnings: list[str]) -> list[str]:
        if any(not warning.strip() or len(warning) > 500 for warning in warnings):
            raise ValueError("safety warnings must be non-empty and at most 500 characters")
        return warnings


class CaseSubmissionCommand(CaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    service_id: int = Field(gt=0)
    service_name: str = Field(min_length=1, max_length=120)
    form_key: str = Field(min_length=1, max_length=120)
    location_id: str = Field(min_length=1, max_length=120)
    location_name: str = Field(min_length=1, max_length=120)
    problem_summary: str = Field(min_length=1, max_length=1000)
    image_path: str | None = Field(default=None, max_length=500)
    image_analysis: CaseImageAnalysis | None = None
    answers: dict[str, AnswerValue] = Field(default_factory=dict)
    preferred_start: datetime
    preferred_end: datetime
    provider_id: str = Field(min_length=1, max_length=120)
    provider_name: str = Field(min_length=1, max_length=120)
    availability_id: str = Field(min_length=1, max_length=120)
    contact: SyntheticContact
    confirmed: bool
    idempotency_key: str = Field(min_length=8, max_length=128)
    source_type: Literal["synthetic"] = "synthetic"

    @field_validator("image_path")
    @classmethod
    def validate_image_path(cls, image_path: str | None) -> str | None:
        return _validate_server_relative_image_path(image_path)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        validate_case_time_window(
            preferred_start=self.preferred_start,
            preferred_end=self.preferred_end,
        )
        _validate_case_image_contract(
            image_path=self.image_path,
            image_analysis=self.image_analysis,
        )
        return self


class ProviderDecisionCommand(CaseModel):
    case_id: str = Field(min_length=1, max_length=120)
    provider_id: str = Field(min_length=1, max_length=120)
    decision: ProviderDecision
    confirmed: bool
    idempotency_key: str = Field(min_length=8, max_length=128)


class CaseAuditEvent(CaseModel):
    event_id: str
    event_type: AuditEventType
    actor_type: Literal["consumer", "provider", "system"]
    actor_id: str
    message: str
    created_at: datetime


class WorkflowCase(CaseModel):
    case_id: str
    session_id: str
    service_id: int
    service_name: str
    form_key: str
    location_id: str
    location_name: str
    problem_summary: str
    image_path: str | None = None
    image_analysis: CaseImageAnalysis | None = None
    answers: dict[str, AnswerValue] = Field(default_factory=dict)
    preferred_start: datetime
    preferred_end: datetime
    provider_id: str
    provider_name: str
    availability_id: str
    contact: SyntheticContact
    status: CaseStatus
    order_no: str | None = None
    source_type: Literal["synthetic"] = "synthetic"
    created_at: datetime
    updated_at: datetime
    version: int = Field(gt=0)
    audit_events: list[CaseAuditEvent] = Field(default_factory=list)

    @field_validator("image_path")
    @classmethod
    def validate_image_path(cls, image_path: str | None) -> str | None:
        return _validate_server_relative_image_path(image_path)

    @model_validator(mode="after")
    def validate_image_contract(self) -> Self:
        _validate_case_image_contract(
            image_path=self.image_path,
            image_analysis=self.image_analysis,
        )
        return self


class IdempotencyRecord(CaseModel):
    key: str
    operation: str
    fingerprint: str
    case_id: str


class ConsumerCaseView(CaseModel):
    case_id: str
    provider_id: str
    provider_name: str
    status: CaseStatus
    order_no: str | None = None
    image_path: str | None = Field(default=None, exclude=True)
    image_analysis: CaseImageAnalysis | None = None
    preferred_start: datetime
    preferred_end: datetime
    source_type: Literal["synthetic"] = "synthetic"
    rejected_provider_ids: list[str] = Field(default_factory=list)
    can_dispatch_again: bool

    @computed_field(return_type=bool)
    @property
    def has_image(self) -> bool:
        """Expose image availability without leaking the server-relative path."""

        return self.image_path is not None


class ProviderContactView(CaseModel):
    access: ContactAccess
    name: str | None = None
    mobile: str | None = None
    address: str | None = None
    source_type: Literal["synthetic"] = "synthetic"


class CaseAuditView(CaseModel):
    event_type: AuditEventType
    label: str
    created_at: datetime


class ProviderCaseSummary(CaseModel):
    case_id: str
    status: CaseStatus
    service_name: str
    location_name: str
    problem_summary: str
    image_path: str | None = Field(default=None, exclude=True)
    image_analysis: CaseImageAnalysis | None = None
    preferred_start: datetime
    preferred_end: datetime
    contact_name_masked: str
    order_no: str | None = None
    source_type: Literal["synthetic"] = "synthetic"
    created_at: datetime
    updated_at: datetime

    @computed_field(return_type=bool)
    @property
    def has_image(self) -> bool:
        return self.image_path is not None


class ProviderCaseDetail(CaseModel):
    case_id: str
    status: CaseStatus
    service_name: str
    location_name: str
    problem_summary: str
    image_path: str | None = Field(default=None, exclude=True)
    image_analysis: CaseImageAnalysis | None = None
    answers: dict[str, AnswerValue] = Field(default_factory=dict)
    preferred_start: datetime
    preferred_end: datetime
    contact: ProviderContactView
    order_no: str | None = None
    source_type: Literal["synthetic"] = "synthetic"
    created_at: datetime
    updated_at: datetime
    audit_events: list[CaseAuditView] = Field(default_factory=list)

    @computed_field(return_type=bool)
    @property
    def has_image(self) -> bool:
        return self.image_path is not None


class DemoProviderIdentity(CaseModel):
    provider_id: str
    display_name: str
    source_type: Literal["synthetic"] = "synthetic"


def _validate_case_image_contract(
    *,
    image_path: str | None,
    image_analysis: CaseImageAnalysis | None,
) -> None:
    if (image_path is None) != (image_analysis is None):
        raise ValueError("image_path and image_analysis must be provided together")
    if image_analysis is not None and image_analysis.confirmed is not True:
        raise ValueError("persisted image_analysis must be explicitly confirmed")
