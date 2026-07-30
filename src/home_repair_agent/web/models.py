from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from home_repair_agent.backend.case_models import (
    CaseStatus,
    ConsumerCaseView,
    DemoProviderIdentity,
    ProviderCaseSummary,
    ProviderDecision,
)
from home_repair_agent.backend.models import (
    ConsultationForm,
    ProviderMatchCandidate,
    ResolvedLocation,
    ServiceSummary,
)

AnswerValue = str | list[str]
ChecklistKey = Literal["service", "location", "consultation"]
SessionState = Literal[
    "collecting_need",
    "clarifying",
    "awaiting_form",
    "matched",
    "no_candidates",
    "dispatch_pending",
    "provider_accepted",
    "provider_rejected",
    "error",
]
ProgressState = Literal["pending", "active", "complete"]


class WebModel(BaseModel):
    """Strict API model for the consumer web demo."""

    model_config = ConfigDict(extra="forbid")


class MessageRequest(WebModel):
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("訊息不可為空白。")
        return value


class FormSubmitRequest(WebModel):
    answers: dict[str, AnswerValue] = Field(default_factory=dict)
    preferred_start: datetime
    preferred_end: datetime

    @field_validator("answers")
    @classmethod
    def validate_answer_limits(
        cls,
        answers: dict[str, AnswerValue],
    ) -> dict[str, AnswerValue]:
        if len(answers) > 30:
            raise ValueError("表單欄位數量超出限制。")
        for topic_key, value in answers.items():
            if len(topic_key) > 120:
                raise ValueError("表單欄位代碼超出限制。")
            values = value if isinstance(value, list) else [value]
            if len(values) > 20 or any(len(item) > 1000 for item in values):
                raise ValueError("表單答案超出限制。")
        return answers

    @model_validator(mode="after")
    def validate_time_window(self) -> Self:
        taipei_offset = timedelta(hours=8)
        if (
            self.preferred_start.tzinfo is None
            or self.preferred_start.utcoffset() != taipei_offset
            or self.preferred_end.tzinfo is None
            or self.preferred_end.utcoffset() != taipei_offset
        ):
            raise ValueError("希望時段必須包含 Asia/Taipei 的 +08:00 時區。")
        if self.preferred_end <= self.preferred_start:
            raise ValueError("結束時間必須晚於開始時間。")
        if self.preferred_end - self.preferred_start > timedelta(hours=12):
            raise ValueError("單次希望時段不可超過 12 小時。")
        return self


class DispatchRequest(WebModel):
    provider_id: str = Field(min_length=1, max_length=120)
    confirmed: bool
    idempotency_key: str = Field(min_length=8, max_length=128)


class ChecklistUpdateRequest(WebModel):
    checked: bool


class ProviderDecisionRequest(WebModel):
    decision: ProviderDecision
    confirmed: bool
    idempotency_key: str = Field(min_length=8, max_length=128)


class ChatMessageView(WebModel):
    message_id: str
    role: Literal["user", "assistant"]
    text: str
    created_at: datetime


class ProviderView(WebModel):
    key: Literal["mock", "huggingface"]
    label: str
    is_external: bool


class ToolTraceView(WebModel):
    name: str
    label: str
    ok: bool


class ProgressStepView(WebModel):
    key: Literal["service", "location", "form", "matching", "dispatch"]
    label: str
    state: ProgressState


class ChecklistItemView(WebModel):
    key: ChecklistKey
    label: str
    checked: bool
    suggested: bool


class SessionView(WebModel):
    session_id: str
    state: SessionState
    provider: ProviderView
    messages: list[ChatMessageView] = Field(default_factory=list)
    service: ServiceSummary | None = None
    location: ResolvedLocation | None = None
    consultation_form: ConsultationForm | None = None
    answers: dict[str, AnswerValue] = Field(default_factory=dict)
    preferred_start: datetime | None = None
    preferred_end: datetime | None = None
    candidates: list[ProviderMatchCandidate] = Field(default_factory=list)
    dispatch: ConsumerCaseView | None = None
    progress: list[ProgressStepView] = Field(default_factory=list)
    checklist: list[ChecklistItemView] = Field(default_factory=list)
    tool_trace: list[ToolTraceView] = Field(default_factory=list)
    data_source: Literal["synthetic"] = "synthetic"
    can_send_message: bool
    can_submit_form: bool
    can_dispatch: bool


class HealthView(WebModel):
    ok: Literal[True] = True
    service: Literal["home-repair-web"] = "home-repair-web"
    mode: Literal["provider-workflow-demo"] = "provider-workflow-demo"


class DemoProviderIdentityListView(WebModel):
    identities: list[DemoProviderIdentity] = Field(default_factory=list)


class ProviderCaseListView(WebModel):
    provider_id: str
    status: CaseStatus | None = None
    count: int = Field(ge=0)
    cases: list[ProviderCaseSummary] = Field(default_factory=list)


class ApiErrorBody(WebModel):
    code: str
    message: str
    fields: dict[str, str] = Field(default_factory=dict)


class ApiErrorResponse(WebModel):
    error: ApiErrorBody
