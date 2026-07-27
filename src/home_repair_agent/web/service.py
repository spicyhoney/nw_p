from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import uuid4

from home_repair_agent.agent.loop import AgentRunner
from home_repair_agent.agent.models import ConversationSession, ToolTraceEntry
from home_repair_agent.agent.ports import ToolClient
from home_repair_agent.backend.models import (
    ConsultationForm,
    FormTopic,
    ProviderMatchCandidate,
    ProviderMatchResult,
    ResolvedLocation,
    ServiceSearchResult,
    ServiceSummary,
)
from home_repair_agent.web.models import (
    AnswerValue,
    ChatMessageView,
    FormSubmitRequest,
    ProgressStepView,
    ProviderView,
    SessionState,
    SessionView,
    ToolTraceView,
)

GREETING = "你好，我是修繕小隊長。請告訴我服務地點和需要處理的問題。"
FORM_LOCKED_MESSAGE = "諮詢表單已準備完成，請先填完表單，或重新開始更正需求。"
MATCHED_LOCKED_MESSAGE = "本次媒合已完成；若要更改需求，請重新開始。"
TOOL_LABELS = {
    "search_services": "確認服務",
    "resolve_location": "確認地點",
    "get_consultation_form": "取得諮詢單",
    "match_service_providers": "媒合候選",
}


class WebSessionError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        fields: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or {}


class WebSessionNotFoundError(WebSessionError):
    def __init__(self) -> None:
        super().__init__(
            code="SESSION_NOT_FOUND",
            message="找不到這個對話，請重新開始。",
        )


class WebSessionConflictError(WebSessionError):
    pass


class WebSessionInputError(WebSessionError):
    pass


class WebSessionUpstreamError(WebSessionError):
    pass


@dataclass
class _SessionRecord:
    session_id: str
    conversation: ConversationSession
    messages: list[ChatMessageView]
    state: SessionState = "collecting_need"
    service: ServiceSummary | None = None
    location: ResolvedLocation | None = None
    consultation_form: ConsultationForm | None = None
    answers: dict[str, AnswerValue] = field(default_factory=dict)
    preferred_start: datetime | None = None
    preferred_end: datetime | None = None
    candidates: list[ProviderMatchCandidate] = field(default_factory=list)
    tool_trace: list[ToolTraceView] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class WebSessionService:
    """Application service for the read-only consumer web workflow."""

    def __init__(
        self,
        *,
        runner: AgentRunner,
        tool_client: ToolClient,
        provider: ProviderView,
        now: Callable[[], datetime],
        max_sessions: int = 200,
    ) -> None:
        self._runner = runner
        self._tool_client = tool_client
        self._provider = provider
        self._now = now
        self._max_sessions = max_sessions
        self._sessions: dict[str, _SessionRecord] = {}
        self._sessions_lock = asyncio.Lock()
        self._tool_client_lock = asyncio.Lock()

    async def create_session(self) -> SessionView:
        async with self._sessions_lock:
            if len(self._sessions) >= self._max_sessions:
                raise WebSessionConflictError(
                    code="SESSION_LIMIT_REACHED",
                    message="目前對話數已達 Demo 上限，請稍後再試。",
                )
            session_id = str(uuid4())
            record = self._new_record(session_id)
            self._sessions[session_id] = record
        return self._to_view(record)

    async def get_session(self, session_id: str) -> SessionView:
        record = await self._get_record(session_id)
        async with record.lock:
            return self._to_view(record)

    async def send_message(self, session_id: str, user_text: str) -> SessionView:
        record = await self._get_record(session_id)
        async with record.lock:
            if record.consultation_form is not None:
                raise WebSessionConflictError(
                    code="FORM_ALREADY_READY",
                    message=FORM_LOCKED_MESSAGE,
                )
            if record.state in {"matched", "no_candidates"}:
                raise WebSessionConflictError(
                    code="MATCH_ALREADY_COMPLETED",
                    message=MATCHED_LOCKED_MESSAGE,
                )

            record.messages.append(self._message("user", user_text))
            async with self._tool_client_lock:
                result = await self._runner.run_turn(
                    session=record.conversation,
                    user_text=user_text,
                )
            record.messages.append(self._message("assistant", result.reply))
            trace_is_valid = self._apply_agent_trace(record, result.tool_trace)
            if result.stop_reason != "completed" or not trace_is_valid:
                record.state = "error"
            else:
                record.state = self._derive_state(record)
            return self._to_view(record)

    async def submit_form(
        self,
        session_id: str,
        submission: FormSubmitRequest,
    ) -> SessionView:
        record = await self._get_record(session_id)
        async with record.lock:
            if (
                record.service is None
                or record.location is None
                or record.consultation_form is None
            ):
                raise WebSessionConflictError(
                    code="FORM_NOT_READY",
                    message="服務、地點或諮詢表單尚未確認，不能進行媒合。",
                )
            if submission.preferred_start <= self._now():
                raise WebSessionInputError(
                    code="INVALID_TIME_WINDOW",
                    message="希望服務時間必須晚於目前時間。",
                    fields={"preferred_time": "請重新選擇未來的服務時段。"},
                )

            clean_answers = _validate_answers(
                form=record.consultation_form,
                supplied=submission.answers,
                preferred_start=submission.preferred_start,
                preferred_end=submission.preferred_end,
            )
            arguments: dict[str, object] = {
                "service_id": record.service.service_id,
                "location_id": record.location.location_id,
                "preferred_start": submission.preferred_start.isoformat(),
                "preferred_end": submission.preferred_end.isoformat(),
                "limit": 3,
            }
            async with self._tool_client_lock:
                execution = await self._tool_client.call_tool(
                    name="match_service_providers",
                    arguments=arguments,
                )
            payload = execution.payload
            if execution.mcp_is_error or payload.get("ok") is not True:
                raise WebSessionUpstreamError(
                    code="MATCHING_UNAVAILABLE",
                    message="目前無法取得可靠的媒合候選，請稍後再試。",
                )
            data = payload.get("data")
            try:
                match_result = ProviderMatchResult.model_validate(data)
            except Exception as error:
                raise WebSessionUpstreamError(
                    code="INVALID_MATCHING_RESPONSE",
                    message="媒合結果格式異常，已停止顯示。",
                ) from error

            record.answers = clean_answers
            record.preferred_start = submission.preferred_start
            record.preferred_end = submission.preferred_end
            record.candidates = list(match_result.candidates)
            record.tool_trace = [
                *record.tool_trace,
                ToolTraceView(
                    name="match_service_providers",
                    label=TOOL_LABELS["match_service_providers"],
                    ok=True,
                ),
            ][-8:]
            record.messages.append(
                self._message(
                    "user",
                    "已提交諮詢表單，並確認希望服務時段。",
                )
            )
            if record.candidates:
                record.messages.append(
                    self._message(
                        "assistant",
                        (
                            f"找到 {len(record.candidates)} 位 synthetic 師傅候選。"
                            "目前只提供候選，尚未建立案件，也未保留時段。"
                        ),
                    )
                )
                record.state = "matched"
            else:
                record.messages.append(
                    self._message(
                        "assistant",
                        "目前沒有符合時段的 synthetic 師傅候選，我不會自行捏造人選。",
                    )
                )
                record.state = "no_candidates"
            return self._to_view(record)

    async def reset_session(self, session_id: str) -> SessionView:
        record = await self._get_record(session_id)
        async with record.lock:
            replacement = self._new_record(session_id)
            self._sessions[session_id] = replacement
            return self._to_view(replacement)

    async def _get_record(self, session_id: str) -> _SessionRecord:
        async with self._sessions_lock:
            record = self._sessions.get(session_id)
        if record is None:
            raise WebSessionNotFoundError()
        return record

    def _new_record(self, session_id: str) -> _SessionRecord:
        return _SessionRecord(
            session_id=session_id,
            conversation=ConversationSession(session_id=session_id),
            messages=[self._message("assistant", GREETING)],
        )

    def _message(
        self,
        role: Literal["user", "assistant"],
        text: str,
    ) -> ChatMessageView:
        return ChatMessageView(
            message_id=str(uuid4()),
            role=role,
            text=text,
            created_at=self._now(),
        )

    def _apply_agent_trace(
        self,
        record: _SessionRecord,
        trace: list[ToolTraceEntry],
    ) -> bool:
        trace_is_valid = True
        for entry in trace:
            ok = entry.result.get("ok") is True and not entry.mcp_is_error
            record.tool_trace.append(
                ToolTraceView(
                    name=entry.name,
                    label=TOOL_LABELS.get(entry.name, "查詢資料"),
                    ok=ok,
                )
            )
            if not ok:
                continue
            data = entry.result.get("data")
            try:
                if entry.name == "search_services":
                    result = ServiceSearchResult.model_validate(data)
                    record.service = result.services[0] if result.count == 1 else None
                elif entry.name == "resolve_location":
                    record.location = ResolvedLocation.model_validate(data)
                elif entry.name == "get_consultation_form":
                    record.consultation_form = ConsultationForm.model_validate(data)
                elif entry.name == "match_service_providers":
                    result = ProviderMatchResult.model_validate(data)
                    record.candidates = list(result.candidates)
            except Exception:  # noqa: BLE001 - invalid tool payload is not exposed
                trace_is_valid = False
        record.tool_trace = record.tool_trace[-8:]
        return trace_is_valid

    def _derive_state(self, record: _SessionRecord) -> SessionState:
        if record.candidates:
            return "matched"
        if record.consultation_form is not None:
            return "awaiting_form"
        if record.service is not None or record.location is not None:
            return "clarifying"
        return "collecting_need"

    def _to_view(self, record: _SessionRecord) -> SessionView:
        progress = _build_progress(record)
        return SessionView(
            session_id=record.session_id,
            state=record.state,
            provider=self._provider,
            messages=list(record.messages),
            service=record.service,
            location=record.location,
            consultation_form=record.consultation_form,
            answers=dict(record.answers),
            preferred_start=record.preferred_start,
            preferred_end=record.preferred_end,
            candidates=list(record.candidates),
            progress=progress,
            tool_trace=list(record.tool_trace),
            can_send_message=record.consultation_form is None
            and record.state not in {"matched", "no_candidates"},
            can_submit_form=record.consultation_form is not None
            and record.service is not None
            and record.location is not None,
        )


def _validate_answers(
    *,
    form: ConsultationForm,
    supplied: dict[str, AnswerValue],
    preferred_start: datetime,
    preferred_end: datetime,
) -> dict[str, AnswerValue]:
    topics = sorted(form.topics, key=lambda topic: topic.sort_order)
    known_keys = {topic.topic_key for topic in topics}
    unknown_keys = set(supplied) - known_keys
    if unknown_keys:
        raise WebSessionInputError(
            code="UNKNOWN_FORM_FIELD",
            message="表單包含未定義欄位，已停止送出。",
            fields={key: "這個欄位不在目前諮詢單中。" for key in sorted(unknown_keys)},
        )

    clean: dict[str, AnswerValue] = {}
    field_errors: dict[str, str] = {}
    for topic in topics:
        if topic.topic_key == "preferred_time":
            clean[topic.topic_key] = f"{preferred_start.isoformat()} / {preferred_end.isoformat()}"
            continue

        value = supplied.get(topic.topic_key)
        if _is_missing(value):
            if topic.is_required:
                field_errors[topic.topic_key] = "此欄位為必填。"
            continue
        try:
            clean[topic.topic_key] = _validate_topic_value(topic, value)
        except (TypeError, ValueError) as error:
            field_errors[topic.topic_key] = str(error)

    if field_errors:
        raise WebSessionInputError(
            code="INVALID_FORM_ANSWERS",
            message="請修正諮詢表單後再送出。",
            fields=field_errors,
        )
    return clean


def _validate_topic_value(topic: FormTopic, value: AnswerValue) -> AnswerValue:
    option_values = {option.value for option in topic.options}
    if topic.input_type == "single_select":
        if not isinstance(value, str) or value not in option_values:
            raise ValueError("請選擇諮詢單提供的其中一個選項。")
        return value
    if topic.input_type == "multi_select":
        if (
            not isinstance(value, list)
            or not value
            or any(item not in option_values for item in value)
        ):
            raise ValueError("請選擇諮詢單提供的有效選項。")
        return list(dict.fromkeys(value))
    if not isinstance(value, str):
        raise TypeError("請輸入文字內容。")
    normalized = value.strip()
    if len(normalized) > 1000:
        raise ValueError("內容不可超過 1000 個字元。")
    return normalized


def _is_missing(value: AnswerValue | None) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return not value


def _build_progress(record: _SessionRecord) -> list[ProgressStepView]:
    form_complete = bool(record.answers)
    matching_complete = record.state in {"matched", "no_candidates"}
    states = {
        "service": "complete" if record.service is not None else "active",
        "location": (
            "complete"
            if record.location is not None
            else "active"
            if record.service is not None
            else "pending"
        ),
        "form": (
            "complete"
            if form_complete
            else "active"
            if record.consultation_form is not None
            else "pending"
        ),
        "matching": "complete" if matching_complete else "pending",
    }
    return [
        ProgressStepView(key="service", label="服務項目", state=states["service"]),
        ProgressStepView(key="location", label="服務地點", state=states["location"]),
        ProgressStepView(key="form", label="諮詢內容", state=states["form"]),
        ProgressStepView(key="matching", label="師傅候選", state=states["matching"]),
    ]
