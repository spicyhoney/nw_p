from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal, Protocol
from uuid import uuid4

from home_repair_agent.agent.huggingface_vision import (
    HuggingFaceVisionError,
    VisionAnalysisResult,
)
from home_repair_agent.agent.loop import AgentRunner
from home_repair_agent.agent.models import ConversationSession, ToolTraceEntry
from home_repair_agent.agent.ports import ToolClient
from home_repair_agent.backend.case_models import (
    CaseImageAnalysis,
    CaseSubmissionCommand,
    ConsumerCaseView,
    SyntheticContact,
)
from home_repair_agent.backend.case_services import (
    CaseWorkflowNotFoundError,
    CaseWorkflowService,
)
from home_repair_agent.backend.media_storage import (
    MediaRead,
    MediaStorage,
    MediaStorageError,
    StoredMedia,
)
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
    ChecklistItemView,
    ChecklistKey,
    DispatchRequest,
    FormSubmitRequest,
    ImageAnalysisConfirmRequest,
    ImageAnalysisView,
    ProgressStepView,
    ProviderView,
    SessionMediaView,
    SessionState,
    SessionView,
    ToolTraceView,
)

GREETING = "你好，我是修繕小隊長。請告訴我服務地點和需要處理的問題。"
FORM_LOCKED_MESSAGE = "諮詢表單已準備完成，請先填完表單，或重新開始更正需求。"
MATCHED_LOCKED_MESSAGE = "本次媒合已完成；若要更改需求，請重新開始。"
WEB_CHAT_TOOL_NAMES = frozenset(
    {
        "search_services",
        "resolve_location",
        "get_consultation_form",
    }
)
TOOL_LABELS = {
    "search_services": "確認服務",
    "resolve_location": "確認地點",
    "get_consultation_form": "取得諮詢單",
    "match_service_providers": "媒合候選",
}
CHECKLIST_ITEMS: tuple[tuple[ChecklistKey, str], ...] = (
    ("service", "修繕需求與服務類型無誤"),
    ("location", "服務地點無誤"),
    ("consultation", "諮詢內容與希望時段無誤"),
)


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


class WebSessionMediaNotFoundError(WebSessionError):
    def __init__(self) -> None:
        super().__init__(
            code="MEDIA_NOT_FOUND",
            message="找不到這張圖片，可能已移除或尚未上傳。",
        )


class WebSessionConflictError(WebSessionError):
    pass


class WebSessionInputError(WebSessionError):
    pass


class WebSessionUpstreamError(WebSessionError):
    pass


class VisionAnalysisClient(Protocol):
    async def analyze(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        context: str | None = None,
    ) -> VisionAnalysisResult: ...


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
    media: StoredMedia | None = None
    image_analysis: ImageAnalysisView | None = None
    checklist: dict[ChecklistKey, bool] = field(
        default_factory=lambda: {key: False for key, _label in CHECKLIST_ITEMS}
    )
    tool_trace: list[ToolTraceView] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class WebSessionService:
    """Application service for consumer consultation, matching and dispatch."""

    def __init__(
        self,
        *,
        runner: AgentRunner,
        tool_client: ToolClient,
        case_workflow: CaseWorkflowService,
        provider: ProviderView,
        now: Callable[[], datetime],
        media_storage: MediaStorage | None = None,
        vision_client: VisionAnalysisClient | None = None,
        max_sessions: int = 200,
    ) -> None:
        self._runner = runner
        self._tool_client = tool_client
        self._case_workflow = case_workflow
        self._provider = provider
        self._now = now
        self._media_storage = media_storage
        self._vision_client = vision_client
        self._max_sessions = max_sessions
        self._sessions: dict[str, _SessionRecord] = {}
        self._sessions_lock = asyncio.Lock()
        self._tool_client_lock = asyncio.Lock()

    @property
    def case_workflow(self) -> CaseWorkflowService:
        return self._case_workflow

    @property
    def image_analysis_available(self) -> bool:
        return self._media_storage is not None and self._vision_client is not None

    @property
    def provider(self) -> ProviderView:
        return self._provider

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
        return await self._to_view(record)

    async def get_session(self, session_id: str) -> SessionView:
        record = await self._get_record(session_id)
        async with record.lock:
            return await self._to_view(record)

    async def upload_image(
        self,
        session_id: str,
        *,
        content: bytes,
        declared_content_type: str | None,
        original_filename: str | None,
        external_processing_confirmed: bool,
    ) -> SessionView:
        """Validate, normalize and analyze one session image without applying it yet."""

        record = await self._get_record(session_id)
        async with record.lock:
            self._require_media_dependencies()
            if self._provider.key != "huggingface":
                raise WebSessionConflictError(
                    code="IMAGE_ANALYSIS_UNAVAILABLE",
                    message="圖片分析只在 Hugging Face AI 模式提供；目前不會自動降級或模擬。",
                )
            if external_processing_confirmed is not True:
                raise WebSessionInputError(
                    code="EXTERNAL_PROCESSING_CONFIRMATION_REQUIRED",
                    message="圖片會送往 Hugging Face 外部服務，請先明確同意。",
                    fields={"external_processing_confirmed": "請勾選外部處理同意。"},
                )
            self._require_media_flow_open(record)
            storage = self._require_media_storage()
            vision = self._require_vision_client()

            try:
                new_media = storage.store_session_image(
                    session_id=session_id,
                    content=content,
                    declared_content_type=declared_content_type,
                    original_filename=original_filename,
                )
                normalized = storage.read_image(new_media)
            except MediaStorageError as error:
                raise _media_storage_web_error(error) from error

            try:
                result = await vision.analyze(
                    image_bytes=normalized.content,
                    mime_type=normalized.content_type,
                )
            except HuggingFaceVisionError as error:
                _delete_media_quietly(storage, new_media)
                raise WebSessionUpstreamError(
                    code="IMAGE_ANALYSIS_FAILED",
                    message="圖片已安全移除，但 Hugging Face 目前無法產生可靠分析，請稍後重試。",
                ) from error
            except Exception as error:
                _delete_media_quietly(storage, new_media)
                raise WebSessionUpstreamError(
                    code="IMAGE_ANALYSIS_FAILED",
                    message="圖片已安全移除，但圖片分析發生非預期錯誤，請稍後重試。",
                ) from error

            previous_media = record.media
            if previous_media is not None:
                try:
                    receipt = storage.stage_delete(media=previous_media)
                except MediaStorageError as error:
                    _delete_media_quietly(storage, new_media)
                    raise _media_storage_web_error(error) from error
            else:
                receipt = None

            if receipt is not None:
                try:
                    storage.commit_delete(receipt)
                except MediaStorageError as error:
                    try:
                        storage.rollback_delete(receipt)
                    finally:
                        _delete_media_quietly(storage, new_media)
                    raise _media_storage_web_error(error) from error
            record.media = new_media
            record.image_analysis = ImageAnalysisView(
                **result.model_dump(),
                confirmed=False,
                correction=None,
            )
            return await self._to_view(record)

    async def get_session_image(self, session_id: str) -> MediaRead:
        record = await self._get_record(session_id)
        async with record.lock:
            if record.media is None:
                raise WebSessionMediaNotFoundError()
            try:
                return self._require_media_storage().read_image(record.media)
            except MediaStorageError as error:
                if error.code == "MEDIA_NOT_FOUND":
                    raise WebSessionMediaNotFoundError() from error
                raise _media_storage_web_error(error) from error

    async def remove_image(self, session_id: str) -> SessionView:
        record = await self._get_record(session_id)
        async with record.lock:
            if record.media is None:
                raise WebSessionMediaNotFoundError()
            if await self._case_workflow.has_session_cases(session_id):
                raise WebSessionConflictError(
                    code="CASE_ALREADY_SUBMITTED",
                    message="案件已送出，圖片必須保留供已指派廠商查看。",
                )
            storage = self._require_media_storage()
            try:
                _delete_media(storage, record.media)
            except MediaStorageError as error:
                raise _media_storage_web_error(error) from error
            record.media = None
            record.image_analysis = None
            return await self._to_view(record)

    async def confirm_image_analysis(
        self,
        session_id: str,
        confirmation: ImageAnalysisConfirmRequest,
    ) -> SessionView:
        """Revalidate a user-edited suggestion through the read tool before applying it."""

        record = await self._get_record(session_id)
        async with record.lock:
            self._require_media_flow_open(record)
            if record.media is None or record.image_analysis is None:
                raise WebSessionMediaNotFoundError()

            async with self._tool_client_lock:
                execution = await self._tool_client.call_tool(
                    name="search_services",
                    arguments={"query": confirmation.service_query, "limit": 5},
                )
            payload = execution.payload
            if execution.mcp_is_error or payload.get("ok") is not True:
                raise WebSessionUpstreamError(
                    code="SERVICE_REVALIDATION_FAILED",
                    message="目前無法用服務目錄重新驗證圖片建議，尚未套用。",
                )
            try:
                result = ServiceSearchResult.model_validate(payload.get("data"))
            except Exception as error:
                raise WebSessionUpstreamError(
                    code="INVALID_SERVICE_RESPONSE",
                    message="服務目錄回應格式異常，圖片建議尚未套用。",
                ) from error
            if result.count != 1:
                raise WebSessionInputError(
                    code="SERVICE_REVALIDATION_AMBIGUOUS",
                    message="這個圖片建議無法唯一對應服務，請把服務描述修得更具體後再確認。",
                    fields={"service_query": "必須唯一對應專案服務目錄中的一項服務。"},
                )

            previous = record.image_analysis
            changed = (
                confirmation.service_query != previous.service_query
                or confirmation.problem_summary != previous.problem_summary
                or confirmation.safety_warnings != previous.safety_warnings
            )
            record.image_analysis = ImageAnalysisView(
                service_query=confirmation.service_query,
                problem_summary=confirmation.problem_summary,
                safety_warnings=confirmation.safety_warnings,
                confidence=previous.confidence,
                uncertain=previous.uncertain,
                confirmed=True,
                correction="使用者已修正模型建議。" if changed else None,
            )
            record.service = result.services[0]
            record.consultation_form = None
            record.tool_trace = [
                *record.tool_trace,
                ToolTraceView(
                    name="search_services",
                    label=TOOL_LABELS["search_services"],
                    ok=True,
                ),
            ][-8:]
            record.messages.extend(
                [
                    self._message("user", "已確認並套用圖片分析建議。"),
                    self._message(
                        "assistant",
                        (
                            f"已用服務目錄確認為「{record.service.name}」。"
                            "圖片仍只是輔助資訊；請再告訴我服務地點。"
                        ),
                    ),
                ]
            )
            record.state = self._derive_state(record)
            return await self._to_view(record)

    async def send_message(self, session_id: str, user_text: str) -> SessionView:
        record = await self._get_record(session_id)
        async with record.lock:
            self._require_confirmed_media(record)
            if record.state in {"matched", "no_candidates"}:
                raise WebSessionConflictError(
                    code="MATCH_ALREADY_COMPLETED",
                    message=MATCHED_LOCKED_MESSAGE,
                )
            if record.consultation_form is not None:
                raise WebSessionConflictError(
                    code="FORM_ALREADY_READY",
                    message=FORM_LOCKED_MESSAGE,
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
            return await self._to_view(record)

    async def submit_form(
        self,
        session_id: str,
        submission: FormSubmitRequest,
    ) -> SessionView:
        record = await self._get_record(session_id)
        async with record.lock:
            self._require_confirmed_media(record)
            if record.state in {"matched", "no_candidates"}:
                raise WebSessionConflictError(
                    code="MATCH_ALREADY_COMPLETED",
                    message=MATCHED_LOCKED_MESSAGE,
                )
            if (
                record.state != "awaiting_form"
                or record.service is None
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
            return await self._to_view(record)

    async def dispatch_case(
        self,
        session_id: str,
        submission: DispatchRequest,
    ) -> SessionView:
        record = await self._get_record(session_id)
        async with record.lock:
            self._require_confirmed_media(record)
            if (
                record.service is None
                or record.location is None
                or record.consultation_form is None
                or record.preferred_start is None
                or record.preferred_end is None
                or not record.candidates
            ):
                raise WebSessionConflictError(
                    code="MATCHING_NOT_READY",
                    message="尚未完成媒合，不能建立派單案件。",
                )
            if record.preferred_start <= self._now():
                raise WebSessionInputError(
                    code="INVALID_TIME_WINDOW",
                    message="原先確認的希望服務時間已過期，請重新選擇未來時段。",
                    fields={"preferred_time": "請重新開始諮詢並選擇未來的服務時段。"},
                )

            candidate = next(
                (item for item in record.candidates if item.provider_id == submission.provider_id),
                None,
            )
            if candidate is None:
                raise WebSessionInputError(
                    code="INVALID_PROVIDER_SELECTION",
                    message="選擇的廠商不在本次媒合候選中。",
                    fields={"provider_id": "請選擇目前畫面提供的候選廠商。"},
                )

            await self._case_workflow.submit_case(
                CaseSubmissionCommand(
                    session_id=record.session_id,
                    service_id=record.service.service_id,
                    service_name=record.service.name,
                    form_key=record.consultation_form.form_key,
                    location_id=record.location.location_id,
                    location_name=record.location.full_name,
                    problem_summary=_problem_summary(record),
                    image_path=record.media.relative_path if record.media is not None else None,
                    image_analysis=(
                        CaseImageAnalysis.model_validate(record.image_analysis.model_dump())
                        if record.image_analysis is not None
                        else None
                    ),
                    answers=dict(record.answers),
                    preferred_start=record.preferred_start,
                    preferred_end=record.preferred_end,
                    provider_id=candidate.provider_id,
                    provider_name=candidate.display_name,
                    availability_id=candidate.availability_id,
                    contact=SyntheticContact(
                        name="林小安",
                        mobile="0912-345-678",
                        address=f"{record.location.full_name} Demo 路 1 號",
                    ),
                    confirmed=submission.confirmed,
                    idempotency_key=submission.idempotency_key,
                )
            )
            return await self._to_view(record)

    async def update_checklist_item(
        self,
        session_id: str,
        *,
        item_key: ChecklistKey,
        checked: bool,
    ) -> SessionView:
        record = await self._get_record(session_id)
        async with record.lock:
            record.checklist[item_key] = checked
            return await self._to_view(record)

    async def reset_session(self, session_id: str) -> SessionView:
        record = await self._get_record(session_id)
        async with record.lock:
            if await self._case_workflow.has_session_cases(session_id):
                raise WebSessionConflictError(
                    code="CASE_ALREADY_SUBMITTED",
                    message="這次諮詢已有派單紀錄；請建立新諮詢，保留原案件稽核資料。",
                )
            if record.media is not None:
                storage = self._require_media_storage()
                try:
                    _delete_media(storage, record.media)
                except MediaStorageError as error:
                    raise _media_storage_web_error(error) from error
            replacement = self._new_record(session_id)
            record.conversation = replacement.conversation
            record.messages = replacement.messages
            record.state = replacement.state
            record.service = None
            record.location = None
            record.consultation_form = None
            record.answers.clear()
            record.preferred_start = None
            record.preferred_end = None
            record.candidates.clear()
            record.media = None
            record.image_analysis = None
            record.checklist = dict(replacement.checklist)
            record.tool_trace.clear()
            return await self._to_view(record)

    async def get_provider_case_image(
        self,
        *,
        provider_id: str,
        case_id: str,
    ) -> MediaRead:
        detail = await self._case_workflow.get_provider_case(
            provider_id=provider_id,
            case_id=case_id,
        )
        if detail.status == "rejected" or detail.image_path is None:
            raise CaseWorkflowNotFoundError()
        media = _stored_media_from_case_path(detail.image_path)
        try:
            return self._require_media_storage().read_image(media)
        except MediaStorageError as error:
            if error.code == "MEDIA_NOT_FOUND":
                raise CaseWorkflowNotFoundError() from error
            raise _media_storage_web_error(error) from error

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

    def _require_media_flow_open(self, record: _SessionRecord) -> None:
        if record.consultation_form is not None or record.state in {
            "matched",
            "no_candidates",
            "dispatch_pending",
            "provider_accepted",
            "provider_rejected",
        }:
            raise WebSessionConflictError(
                code="MEDIA_FLOW_LOCKED",
                message="諮詢表單或案件流程已開始；請重新開始後再更換圖片。",
            )

    @staticmethod
    def _require_confirmed_media(record: _SessionRecord) -> None:
        if record.media is not None and (
            record.image_analysis is None or not record.image_analysis.confirmed
        ):
            raise WebSessionConflictError(
                code="IMAGE_CONFIRMATION_REQUIRED",
                message="請先確認或移除圖片分析建議，再繼續諮詢與媒合。",
            )

    def _require_media_dependencies(self) -> None:
        if not self.image_analysis_available:
            raise WebSessionConflictError(
                code="IMAGE_ANALYSIS_UNAVAILABLE",
                message="目前未設定圖片分析服務；系統不會靜默改用模擬結果。",
            )

    def _require_media_storage(self) -> MediaStorage:
        if self._media_storage is None:
            raise WebSessionConflictError(
                code="IMAGE_STORAGE_UNAVAILABLE",
                message="目前未設定安全圖片儲存，無法處理圖片。",
            )
        return self._media_storage

    def _require_vision_client(self) -> VisionAnalysisClient:
        if self._vision_client is None:
            raise WebSessionConflictError(
                code="IMAGE_ANALYSIS_UNAVAILABLE",
                message="目前未設定圖片分析服務；系統不會靜默改用模擬結果。",
            )
        return self._vision_client

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
            is_allowed = entry.name in WEB_CHAT_TOOL_NAMES
            ok = is_allowed and entry.result.get("ok") is True and not entry.mcp_is_error
            record.tool_trace.append(
                ToolTraceView(
                    name=entry.name,
                    label=TOOL_LABELS.get(entry.name, "查詢資料"),
                    ok=ok,
                )
            )
            if not is_allowed:
                trace_is_valid = False
                continue
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

    async def _to_view(self, record: _SessionRecord) -> SessionView:
        dispatch = await self._case_workflow.get_consumer_case(record.session_id)
        if dispatch is not None:
            next_state: SessionState = {
                "pending_provider": "dispatch_pending",
                "accepted": "provider_accepted",
                "rejected": "provider_rejected",
            }[dispatch.status]
            if record.state != next_state:
                record.state = next_state
                record.messages.append(
                    self._message(
                        "assistant",
                        _dispatch_status_message(dispatch),
                    )
                )

        rejected_provider_ids = (
            set(dispatch.rejected_provider_ids) if dispatch is not None else set()
        )
        can_dispatch = bool(record.candidates) and (
            dispatch is None
            or (
                dispatch.can_dispatch_again
                and any(
                    candidate.provider_id not in rejected_provider_ids
                    for candidate in record.candidates
                )
            )
        )
        media_confirmed = record.media is None or (
            record.image_analysis is not None and record.image_analysis.confirmed
        )
        progress = _build_progress(record, dispatch=dispatch)
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
            dispatch=dispatch,
            media=(
                SessionMediaView(
                    media_id=record.media.media_id,
                    content_type=record.media.content_type,
                    analysis=record.image_analysis,
                )
                if record.media is not None and record.image_analysis is not None
                else None
            ),
            progress=progress,
            checklist=_build_checklist(record),
            tool_trace=list(record.tool_trace),
            can_send_message=media_confirmed
            and record.consultation_form is None
            and record.state not in {"matched", "no_candidates"},
            can_submit_form=media_confirmed
            and record.state == "awaiting_form"
            and record.consultation_form is not None
            and record.service is not None
            and record.location is not None,
            can_dispatch=media_confirmed and can_dispatch,
        )


def _build_checklist(record: _SessionRecord) -> list[ChecklistItemView]:
    suggestions: dict[ChecklistKey, bool] = {
        "service": record.service is not None,
        "location": record.location is not None,
        "consultation": bool(record.answers)
        and record.preferred_start is not None
        and record.preferred_end is not None,
    }
    return [
        ChecklistItemView(
            key=key,
            label=label,
            checked=record.checklist[key],
            suggested=suggestions[key],
        )
        for key, label in CHECKLIST_ITEMS
    ]


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


def _build_progress(
    record: _SessionRecord,
    *,
    dispatch: ConsumerCaseView | None,
) -> list[ProgressStepView]:
    form_complete = bool(record.answers)
    matching_complete = bool(record.candidates) or record.state == "no_candidates"
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
        "dispatch": (
            "complete"
            if dispatch is not None and dispatch.status == "accepted"
            else "active"
            if dispatch is not None
            else "pending"
        ),
    }
    return [
        ProgressStepView(key="service", label="服務項目", state=states["service"]),
        ProgressStepView(key="location", label="服務地點", state=states["location"]),
        ProgressStepView(key="form", label="諮詢內容", state=states["form"]),
        ProgressStepView(key="matching", label="師傅候選", state=states["matching"]),
        ProgressStepView(key="dispatch", label="派單狀態", state=states["dispatch"]),
    ]


def _problem_summary(record: _SessionRecord) -> str:
    category_value = record.answers.get("issue_category")
    category_label = ""
    if isinstance(category_value, str) and record.consultation_form is not None:
        topic = next(
            (
                item
                for item in record.consultation_form.topics
                if item.topic_key == "issue_category"
            ),
            None,
        )
        if topic is not None:
            option = next(
                (item for item in topic.options if item.value == category_value),
                None,
            )
            category_label = option.label if option is not None else ""

    notes = record.answers.get("notes")
    notes_text = notes.strip() if isinstance(notes, str) else ""
    parts = [
        part
        for part in (
            category_label or record.service.name if record.service is not None else "",
            notes_text,
        )
        if part
    ]
    return "｜".join(parts)[:1000] or "已完成結構化修繕諮詢"


def _dispatch_status_message(dispatch: ConsumerCaseView) -> str:
    if dispatch.status == "pending_provider":
        return f"案件 {dispatch.case_id} 已派給 {dispatch.provider_name}，目前等待廠商回覆。"
    if dispatch.status == "accepted":
        return f"{dispatch.provider_name} 已接單，Demo 訂單編號為 {dispatch.order_no}。"
    return f"{dispatch.provider_name} 已拒絕本次案件，你可以改選其他尚未拒絕的候選廠商。"


def _media_storage_web_error(error: MediaStorageError) -> WebSessionError:
    if error.code in {
        "INVALID_MEDIA_CONTENT",
        "INVALID_IMAGE",
        "UNSUPPORTED_IMAGE_TYPE",
        "MEDIA_TOO_LARGE",
        "IMAGE_NORMALIZATION_FAILED",
    }:
        return WebSessionInputError(code=error.code, message=error.message)
    if error.code == "MEDIA_NOT_FOUND":
        return WebSessionMediaNotFoundError()
    return WebSessionUpstreamError(
        code="MEDIA_STORAGE_UNAVAILABLE",
        message="圖片儲存目前無法安全完成操作，請稍後重試。",
    )


def _delete_media_quietly(storage: MediaStorage, media: StoredMedia) -> None:
    try:
        _delete_media(storage, media)
    except MediaStorageError:
        # The original provider/storage exception remains the public failure.
        # No path or image bytes are included in either error.
        return


def _delete_media(storage: MediaStorage, media: StoredMedia) -> None:
    receipt = storage.stage_delete(media=media)
    try:
        storage.commit_delete(receipt)
    except MediaStorageError:
        storage.rollback_delete(receipt)
        raise


def _stored_media_from_case_path(image_path: str) -> StoredMedia:
    path = PurePosixPath(image_path)
    content_types = {
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    content_type = content_types.get(path.suffix.lower())
    if content_type is None or not path.stem:
        raise CaseWorkflowNotFoundError()
    return StoredMedia(
        media_id=path.stem,
        relative_path=image_path,
        content_type=content_type,
        byte_size=0,
    )
