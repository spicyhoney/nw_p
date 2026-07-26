from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
