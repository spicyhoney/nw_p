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
from home_repair_agent.backend.repair_conversation import RepairBranch

AnswerValue = str | list[str]
ChecklistKey = Literal["service", "location", "consultation"]
ServiceSource = Literal["text_tool", "image_confirmed"]
SessionState = Literal[
    "collecting_need",
    "routing_pending",
    "replacement_pending",
    "clarifying",
    "awaiting_form",
    "awaiting_summary_confirmation",
    "matched",
    "no_candidates",
    "dispatch_pending",
    "provider_accepted",
    "provider_rejected",
    "error",
]
ProgressState = Literal["pending", "active", "complete"]
TaskStatus = Literal[
    "routing",
    "collecting",
    "replacement_pending",
    "awaiting_form",
    "awaiting_summary_confirmation",
    "summary_confirmed",
    "matched",
    "dispatched",
    "error",
]


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


class BranchConfirmRequest(WebModel):
    branch: RepairBranch
    confirm: bool


class SummaryConfirmRequest(WebModel):
    active_task_id: str = Field(min_length=1, max_length=128)
    summary_id: str = Field(min_length=1, max_length=128)
    summary_version: int = Field(ge=1)
    confirm: bool


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
    key: Literal["mock", "huggingface", "bedrock"]
    label: str
    is_external: bool


class RepairRoutingView(WebModel):
    confidence: Literal["high", "medium", "low"]
    alternatives: list[RepairBranch] = Field(default_factory=list)
    unsupported: bool
    clarification_question: str | None = None
    canonical_service_id: int | None = None
    repair_branch: RepairBranch | None = None
    pending_branch: RepairBranch | None = None
    confirmed_branch: RepairBranch | None = None
    replacement_pending: bool = False


class ConsultationSummaryView(WebModel):
    summary_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    confirmed: bool
    canonical_service_id: Literal[17] = 17
    service_name: str
    branch: RepairBranch
    location_id: str
    location_name: str
    preferred_start: datetime
    preferred_end: datetime
    form_key: Literal["repair_form_v1"] = "repair_form_v1"
    form_version: int = Field(gt=0)
    answers: dict[str, AnswerValue] = Field(default_factory=dict)
    synthetic_contact: str = "林小安 · 0912-345-678 · Demo 地址"
    shared_slots_need_confirmation: bool = False


class ActiveConsultationTaskView(WebModel):
    active_task_id: str = Field(min_length=1, max_length=128)
    status: TaskStatus
    branch: RepairBranch | None = None
    collected_fields: dict[str, AnswerValue] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    summary: ConsultationSummaryView | None = None
    shared_slots_need_confirmation: bool = False


class ImageAnalysisView(WebModel):
    analysis_revision: str = Field(min_length=16, max_length=128)
    service_query: str = Field(min_length=1, max_length=300)
    problem_summary: str = Field(min_length=1, max_length=1000)
    safety_warnings: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0, le=1)
    uncertain: bool
    confirmed: bool = False
    correction: str | None = Field(default=None, max_length=1000)


class SessionMediaView(WebModel):
    media_id: str
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    branch: RepairBranch | None = None
    analysis: ImageAnalysisView


class ImageAnalysisConfirmRequest(WebModel):
    media_id: str = Field(min_length=1, max_length=128)
    analysis_revision: str = Field(min_length=16, max_length=128)
    service_query: str = Field(min_length=1, max_length=300)
    problem_summary: str = Field(min_length=1, max_length=1000)
    safety_warnings: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("service_query", "problem_summary")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("欄位不可為空白。")
        return normalized

    @field_validator("safety_warnings")
    @classmethod
    def normalize_warnings(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if any(len(value) > 500 for value in normalized):
            raise ValueError("單一安全提醒不可超過 500 個字元。")
        return list(dict.fromkeys(normalized))


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
    repair_routing: RepairRoutingView | None = None
    active_task: ActiveConsultationTaskView | None = None
    service: ServiceSummary | None = None
    service_source: ServiceSource | None = None
    location: ResolvedLocation | None = None
    consultation_form: ConsultationForm | None = None
    guided_form_active: bool = False
    answers: dict[str, AnswerValue] = Field(default_factory=dict)
    preferred_start: datetime | None = None
    preferred_end: datetime | None = None
    candidates: list[ProviderMatchCandidate] = Field(default_factory=list)
    dispatch: ConsumerCaseView | None = None
    media: SessionMediaView | None = None
    progress: list[ProgressStepView] = Field(default_factory=list)
    checklist: list[ChecklistItemView] = Field(default_factory=list)
    tool_trace: list[ToolTraceView] = Field(default_factory=list)
    data_source: Literal["synthetic"] = "synthetic"
    can_send_message: bool
    can_submit_form: bool
    can_confirm_summary: bool
    can_dispatch: bool


class HealthView(WebModel):
    ok: Literal[True] = True
    service: Literal["home-repair-web"] = "home-repair-web"
    mode: Literal["provider-workflow-demo"] = "provider-workflow-demo"
    model_provider: Literal["mock", "huggingface", "bedrock"]
    media_provider: Literal["huggingface"] | None = None


class SpeechTranscriptionView(WebModel):
    text: str = Field(min_length=1, max_length=1000)
    model_id: str = Field(min_length=1, max_length=200)
    provider: Literal["huggingface_space"] = "huggingface_space"
    needs_user_confirmation: Literal[True] = True


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
