from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReadModel(BaseModel):
    """Strict JSON-serializable model returned by read-only services."""

    model_config = ConfigDict(extra="forbid")


class ServiceSummary(ReadModel):
    service_id: int
    service_vendor_id: int
    vendor_name: str
    service_type: str | None = None
    service_type_name: str | None = None
    name: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)


class ServiceSearchResult(ReadModel):
    query: str | None
    count: int = Field(ge=0)
    services: list[ServiceSummary] = Field(default_factory=list)


class ResolvedLocation(ReadModel):
    location_id: str
    county_name: str
    district_name: str
    full_name: str
    postal_code: str | None = None


class FormOption(ReadModel):
    option_key: str
    value: str
    label: str
    sort_order: int = Field(gt=0)


class FormTopic(ReadModel):
    topic_key: str
    input_type: str
    title: str
    is_required: bool
    sort_order: int = Field(gt=0)
    config: dict[str, Any] = Field(default_factory=dict)
    options: list[FormOption] = Field(default_factory=list)


class ConsultationForm(ReadModel):
    form_key: str
    service_id: int
    version: int = Field(gt=0)
    name: str
    description: str = ""
    topics: list[FormTopic] = Field(default_factory=list)


class AvailableProviderSlot(ReadModel):
    provider_id: str
    display_name: str
    service_id: int = Field(gt=0)
    rating: float = Field(ge=0, le=5)
    completed_jobs: int = Field(ge=0)
    base_inspection_fee: float = Field(ge=0)
    location_id: str
    location_name: str
    availability_id: str
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def validate_time_window(self) -> Self:
        if (
            self.starts_at.tzinfo is None
            or self.starts_at.utcoffset() is None
            or self.ends_at.tzinfo is None
            or self.ends_at.utcoffset() is None
        ):
            raise ValueError("provider availability must include a timezone")
        if self.ends_at <= self.starts_at:
            raise ValueError("provider availability must end after it starts")
        return self


class MatchScoreBreakdown(ReadModel):
    schedule_fit: float = Field(ge=0, le=1)
    rating: float = Field(ge=0, le=1)
    experience: float = Field(ge=0, le=1)
    fee: float = Field(ge=0, le=1)


class ProviderMatchCandidate(ReadModel):
    provider_id: str
    display_name: str
    location_name: str
    availability_id: str
    starts_at: datetime
    ends_at: datetime
    rating: float = Field(ge=0, le=5)
    completed_jobs: int = Field(ge=0)
    base_inspection_fee: float = Field(ge=0)
    match_score: float = Field(ge=0, le=1)
    score_breakdown: MatchScoreBreakdown
    reasons: list[str] = Field(default_factory=list)
    source_type: Literal["synthetic"] = "synthetic"


class ProviderMatchResult(ReadModel):
    service_id: int = Field(gt=0)
    location_id: str
    preferred_start: datetime | None = None
    preferred_end: datetime | None = None
    scoring_policy: Literal["matching_v1"] = "matching_v1"
    data_source: Literal["synthetic"] = "synthetic"
    count: int = Field(ge=0)
    candidates: list[ProviderMatchCandidate] = Field(default_factory=list)
