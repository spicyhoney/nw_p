from __future__ import annotations

import asyncio
import mimetypes
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import FastAPI, File, Form, Header, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from mcp.shared.memory import create_connected_server_and_client_session

if sys.platform == "win32":
    # psycopg async connections require a selector-based loop on Windows.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from home_repair_agent.agent.agentcore_mcp_client import create_agentcore_mcp_tool_client
from home_repair_agent.agent.demo import (
    TAIPEI_TIMEZONE,
    DemoReadRepository,
    _resolve_model_client,
)
from home_repair_agent.agent.huggingface_vision import HuggingFaceVisionClient
from home_repair_agent.agent.loop import AgentRunner
from home_repair_agent.agent.mcp_client import MCPToolClient
from home_repair_agent.agent.ports import ToolClient
from home_repair_agent.backend.case_models import (
    CaseStatus,
    DemoProviderIdentity,
    ProviderCaseDetail,
    ProviderDecisionCommand,
)
from home_repair_agent.backend.case_ports import CaseWorkflowRepository
from home_repair_agent.backend.case_services import (
    CaseWorkflowConflictError,
    CaseWorkflowError,
    CaseWorkflowInputError,
    CaseWorkflowNotFoundError,
    CaseWorkflowService,
)
from home_repair_agent.backend.media_storage import MAX_UPLOAD_BYTES, LocalMediaStorage
from home_repair_agent.backend.services import ReadServiceLayer
from home_repair_agent.mcp_server.server import create_mcp_server
from home_repair_agent.web.demo_case_repository import DemoCaseWorkflowRepository
from home_repair_agent.web.models import (
    ApiErrorBody,
    ApiErrorResponse,
    BranchConfirmRequest,
    ChecklistKey,
    ChecklistUpdateRequest,
    DemoProviderIdentityListView,
    DispatchRequest,
    FormSubmitRequest,
    HealthView,
    ImageAnalysisConfirmRequest,
    MessageRequest,
    ProviderCaseListView,
    ProviderDecisionRequest,
    ProviderView,
    SessionView,
    SpeechTranscriptionView,
    SummaryConfirmRequest,
)
from home_repair_agent.web.service import (
    WEB_CHAT_TOOL_NAMES,
    WebSessionConflictError,
    WebSessionError,
    WebSessionInputError,
    WebSessionMediaNotFoundError,
    WebSessionNotFoundError,
    WebSessionService,
    WebSessionUpstreamError,
)
from home_repair_agent.web.speech import (
    MAX_SPEECH_UPLOAD_BYTES,
    HuggingFaceGradioSpeechToTextClient,
    SpeechToTextInputError,
    SpeechToTextPort,
    SpeechToTextRequestError,
    SpeechToTextResponseError,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
mimetypes.add_type("image/webp", ".webp")
DEMO_PROVIDER_IDENTITIES = (
    DemoProviderIdentity(
        provider_id="SYN-PROVIDER-001",
        display_name="安心修繕 A 組",
    ),
    DemoProviderIdentity(
        provider_id="SYN-PROVIDER-002",
        display_name="城市水電 B 組",
    ),
)
DEMO_PROVIDER_IDS = frozenset(identity.provider_id for identity in DEMO_PROVIDER_IDENTITIES)
DemoProviderHeader = Annotated[str, Header(alias="X-Demo-Provider-Id")]
IPAddress = IPv4Address | IPv6Address


def _resolve_demo_ip_allowlist() -> tuple[frozenset[IPAddress], bool] | None:
    """Read the opt-in public Demo allowlist without accepting ranges or hostnames."""

    raw_allowed_ips = os.getenv("DEMO_ALLOWED_IPS")
    raw_trust_cf = os.getenv("DEMO_TRUST_CF_CONNECTING_IP")
    trust_cf_connecting_ip = False
    if raw_trust_cf is not None:
        normalized_trust = raw_trust_cf.strip().lower()
        if normalized_trust not in {"true", "false"}:
            raise RuntimeError("DEMO_TRUST_CF_CONNECTING_IP must be true or false")
        trust_cf_connecting_ip = normalized_trust == "true"

    if raw_allowed_ips is None:
        if trust_cf_connecting_ip:
            raise RuntimeError("DEMO_TRUST_CF_CONNECTING_IP=true requires DEMO_ALLOWED_IPS")
        return None

    values = raw_allowed_ips.split(",")
    if not values or any(not value.strip() for value in values):
        raise RuntimeError("DEMO_ALLOWED_IPS must contain comma-separated exact IP addresses")

    allowed_ips: set[IPAddress] = set()
    for value in values:
        try:
            allowed_ips.add(ip_address(value.strip()))
        except ValueError as error:
            raise RuntimeError(
                "DEMO_ALLOWED_IPS must contain comma-separated exact IP addresses"
            ) from error
    return frozenset(allowed_ips), trust_cf_connecting_ip


def _request_ip(
    request: Request,
    *,
    trust_cf_connecting_ip: bool,
) -> IPAddress | None:
    """Resolve a request IP, trusting Cloudflare only across a loopback hop."""

    if request.client is None:
        return None
    try:
        direct_ip = ip_address(request.client.host)
    except ValueError:
        return None

    forwarded_value = request.headers.get("CF-Connecting-IP")
    if trust_cf_connecting_ip and direct_ip.is_loopback and forwarded_value is not None:
        try:
            return ip_address(forwarded_value.strip())
        except ValueError:
            return None
    return direct_ip


def _resolve_case_repository() -> CaseWorkflowRepository:
    repository_key = os.getenv("WEB_CASE_REPOSITORY", "memory").strip().lower()
    if repository_key == "memory":
        return DemoCaseWorkflowRepository()
    if repository_key == "postgres":
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError("WEB_CASE_REPOSITORY=postgres requires a non-empty DATABASE_URL")
        from home_repair_agent.backend.postgres_case_repository import (
            PostgresCaseWorkflowRepository,
        )

        return PostgresCaseWorkflowRepository(database_url)
    raise RuntimeError("WEB_CASE_REPOSITORY must be one of: memory, postgres")


def _resolve_media_provider(model_provider_key: str) -> str | None:
    """Resolve rich-media inference independently from the text model.

    Existing Hugging Face text mode keeps its media behavior for backwards
    compatibility.  Other text providers must explicitly opt in so Bedrock or
    Mock mode can never silently start sending media to an external service.
    """

    configured = os.getenv("WEB_MEDIA_PROVIDER")
    if configured is None:
        return "huggingface" if model_provider_key == "huggingface" else None
    media_provider = configured.strip().lower()
    if media_provider == "none":
        return None
    if media_provider == "huggingface":
        return media_provider
    raise RuntimeError("WEB_MEDIA_PROVIDER must be one of: none, huggingface")


@asynccontextmanager
async def _tool_client_context(
    repository: DemoReadRepository,
) -> AsyncIterator[ToolClient]:
    """Create the configured read-only tool transport without fallback.

    Case workflow writes deliberately remain local to the web process.  The
    AgentCore transport is only the existing read-only MCP tool surface.
    """

    transport = os.getenv("TOOL_TRANSPORT", "local").strip().lower()
    if transport == "local":
        mcp_server = create_mcp_server(ReadServiceLayer(repository))
        async with create_connected_server_and_client_session(
            mcp_server,
            raise_exceptions=True,
        ) as mcp_session:
            yield MCPToolClient(mcp_session)
        return

    if transport == "agentcore_remote_mcp":
        async with create_agentcore_mcp_tool_client() as tool_client:
            yield tool_client
        return

    raise RuntimeError("TOOL_TRANSPORT must be one of: local, agentcore_remote_mcp")


def create_app(
    *,
    session_service: WebSessionService | None = None,
    case_workflow: CaseWorkflowService | None = None,
    reference_time: datetime | None = None,
    speech_to_text_client: SpeechToTextPort | None = None,
) -> FastAPI:
    demo_ip_allowlist = _resolve_demo_ip_allowlist()
    if (
        session_service is not None
        and case_workflow is not None
        and case_workflow is not session_service.case_workflow
    ):
        raise ValueError(
            "session_service and case_workflow must share the same CaseWorkflowService"
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        now = (
            (lambda: reference_time)
            if reference_time is not None
            else lambda: datetime.now(TAIPEI_TIMEZONE)
        )
        if session_service is not None:
            app.state.web_sessions = session_service
            app.state.case_workflow = session_service.case_workflow
            app.state.speech_to_text = speech_to_text_client
            app.state.media_provider = (
                "huggingface"
                if speech_to_text_client is not None and session_service.image_analysis_available
                else None
            )
            yield
            return

        provider_key = os.getenv(
            "WEB_MODEL_PROVIDER",
            os.getenv("MODEL_PROVIDER", "mock"),
        ).strip()
        model_client, provider_label = _resolve_model_client(provider_key)
        media_provider_key = _resolve_media_provider(provider_key)
        media_storage = LocalMediaStorage()
        vision_client = (
            HuggingFaceVisionClient.from_environment()
            if media_provider_key == "huggingface"
            else None
        )
        speech_client = speech_to_text_client or (
            HuggingFaceGradioSpeechToTextClient.from_environment()
            if media_provider_key == "huggingface"
            else None
        )
        repository = DemoReadRepository(reference_time=reference_time)
        workflow = (
            case_workflow
            if case_workflow is not None
            else CaseWorkflowService(
                _resolve_case_repository(),
                now=now,
            )
        )
        async with _tool_client_context(repository) as tool_client:
            app.state.web_sessions = WebSessionService(
                runner=AgentRunner(
                    model_client=model_client,
                    tool_client=tool_client,
                    allowed_tool_names=set(WEB_CHAT_TOOL_NAMES),
                ),
                tool_client=tool_client,
                case_workflow=workflow,
                provider=ProviderView(
                    key=provider_key,
                    label=provider_label,
                    is_external=provider_key in {"huggingface", "bedrock"},
                ),
                now=now,
                media_storage=media_storage,
                vision_client=vision_client,
            )
            app.state.case_workflow = workflow
            app.state.speech_to_text = speech_client
            app.state.media_provider = media_provider_key
            yield

    app = FastAPI(
        title="修繕小隊長 Web Demo",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def enforce_demo_ip_allowlist(request: Request, call_next: Any) -> Any:
        if demo_ip_allowlist is None:
            return await call_next(request)

        allowed_ips, trust_cf_connecting_ip = demo_ip_allowlist
        request_ip = _request_ip(
            request,
            trust_cf_connecting_ip=trust_cf_connecting_ip,
        )
        if request_ip is not None and (request_ip.is_loopback or request_ip in allowed_ips):
            return await call_next(request)
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "DEMO_IP_NOT_ALLOWED",
                    "message": "This Demo is restricted to approved networks.",
                }
            },
        )

    @app.exception_handler(WebSessionNotFoundError)
    async def handle_not_found(
        _request: Request,
        error: WebSessionNotFoundError,
    ) -> JSONResponse:
        return _error_response(error, status_code=404)

    @app.exception_handler(WebSessionMediaNotFoundError)
    async def handle_media_not_found(
        _request: Request,
        error: WebSessionMediaNotFoundError,
    ) -> JSONResponse:
        return _error_response(error, status_code=404)

    @app.exception_handler(WebSessionInputError)
    async def handle_input_error(
        _request: Request,
        error: WebSessionInputError,
    ) -> JSONResponse:
        return _error_response(error, status_code=422)

    @app.exception_handler(WebSessionConflictError)
    async def handle_conflict(
        _request: Request,
        error: WebSessionConflictError,
    ) -> JSONResponse:
        return _error_response(error, status_code=409)

    @app.exception_handler(WebSessionUpstreamError)
    async def handle_upstream_error(
        _request: Request,
        error: WebSessionUpstreamError,
    ) -> JSONResponse:
        return _error_response(error, status_code=503)

    @app.exception_handler(CaseWorkflowNotFoundError)
    async def handle_case_not_found(
        _request: Request,
        error: CaseWorkflowNotFoundError,
    ) -> JSONResponse:
        return _case_error_response(error, status_code=404)

    @app.exception_handler(CaseWorkflowInputError)
    async def handle_case_input(
        _request: Request,
        error: CaseWorkflowInputError,
    ) -> JSONResponse:
        return _case_error_response(error, status_code=422)

    @app.exception_handler(CaseWorkflowConflictError)
    async def handle_case_conflict(
        _request: Request,
        error: CaseWorkflowConflictError,
    ) -> JSONResponse:
        return _case_error_response(error, status_code=409)

    @app.middleware("http")
    async def disable_api_caching(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self'; "
            "script-src 'self'; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
        return response

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/provider", include_in_schema=False)
    async def provider_index() -> FileResponse:
        return FileResponse(STATIC_DIR / "provider.html")

    @app.get("/api/health", response_model=HealthView)
    async def health(request: Request) -> HealthView:
        return HealthView(
            model_provider=_session_service(request).provider.key,
            media_provider=getattr(request.app.state, "media_provider", None),
        )

    @app.post(
        "/api/sessions",
        response_model=SessionView,
        status_code=201,
    )
    async def create_session(request: Request) -> SessionView:
        return await _session_service(request).create_session()

    @app.get("/api/sessions/{session_id}", response_model=SessionView)
    async def get_session(session_id: str, request: Request) -> SessionView:
        return await _session_service(request).get_session(session_id)

    @app.post(
        "/api/sessions/{session_id}/speech/transcribe",
        response_model=SpeechTranscriptionView,
    )
    async def transcribe_session_audio(
        session_id: str,
        request: Request,
        file: Annotated[UploadFile, File()],
        external_processing_confirmed: Annotated[bool, Form()],
    ) -> SpeechTranscriptionView:
        await _session_service(request).get_session(session_id)
        speech_client = getattr(request.app.state, "speech_to_text", None)
        if speech_client is None:
            raise WebSessionConflictError(
                code="VOICE_INPUT_UNAVAILABLE",
                message="語音輸入服務尚未設定；系統不會改用 Mock 或其他供應商。",
            )
        if not external_processing_confirmed:
            raise WebSessionInputError(
                code="VOICE_EXTERNAL_CONSENT_REQUIRED",
                message="請先明確同意將這段測試錄音送至外部 Hugging Face Space。",
            )
        try:
            content = await file.read(MAX_SPEECH_UPLOAD_BYTES + 1)
        finally:
            await file.close()
        try:
            transcript = await speech_client.transcribe(
                content,
                content_type=file.content_type or "",
            )
        except SpeechToTextInputError as error:
            raise WebSessionInputError(
                code="INVALID_VOICE_AUDIO",
                message=(
                    "無法處理這段錄音；請使用瀏覽器支援的 WebM、Ogg、MP4、WAV 或 "
                    "MP3，且大小不超過 6 MB。"
                ),
            ) from error
        except (SpeechToTextRequestError, SpeechToTextResponseError) as error:
            raise WebSessionUpstreamError(
                code="VOICE_TRANSCRIPTION_FAILED",
                message=("台語語音辨識服務目前無法完成處理，沒有改用 Mock；請稍後再試或改用文字。"),
            ) from error
        return SpeechTranscriptionView(
            text=transcript.text,
            model_id=transcript.model_id,
        )

    @app.post(
        "/api/sessions/{session_id}/image",
        response_model=SessionView,
    )
    async def upload_session_image(
        session_id: str,
        request: Request,
        file: Annotated[UploadFile, File()],
        external_processing_confirmed: Annotated[bool, Form()],
    ) -> SessionView:
        try:
            content = await file.read(MAX_UPLOAD_BYTES + 1)
        finally:
            await file.close()
        return await _session_service(request).upload_image(
            session_id,
            content=content,
            declared_content_type=file.content_type,
            original_filename=file.filename,
            external_processing_confirmed=external_processing_confirmed,
        )

    @app.get("/api/sessions/{session_id}/image")
    async def get_session_image(session_id: str, request: Request) -> Response:
        media = await _session_service(request).get_session_image(session_id)
        return _image_response(media.content, media.content_type)

    @app.delete(
        "/api/sessions/{session_id}/image",
        response_model=SessionView,
    )
    async def remove_session_image(session_id: str, request: Request) -> SessionView:
        return await _session_service(request).remove_image(session_id)

    @app.post(
        "/api/sessions/{session_id}/image/confirm",
        response_model=SessionView,
    )
    async def confirm_session_image(
        session_id: str,
        payload: ImageAnalysisConfirmRequest,
        request: Request,
    ) -> SessionView:
        return await _session_service(request).confirm_image_analysis(
            session_id,
            payload,
        )

    @app.post(
        "/api/sessions/{session_id}/branch/confirm",
        response_model=SessionView,
    )
    async def confirm_session_branch(
        session_id: str,
        payload: BranchConfirmRequest,
        request: Request,
    ) -> SessionView:
        return await _session_service(request).confirm_branch(session_id, payload)

    @app.post(
        "/api/sessions/{session_id}/messages",
        response_model=SessionView,
    )
    async def send_message(
        session_id: str,
        payload: MessageRequest,
        request: Request,
    ) -> SessionView:
        return await _session_service(request).send_message(session_id, payload.text)

    @app.post(
        "/api/sessions/{session_id}/form",
        response_model=SessionView,
    )
    async def submit_form(
        session_id: str,
        payload: FormSubmitRequest,
        request: Request,
    ) -> SessionView:
        return await _session_service(request).submit_form(session_id, payload)

    @app.post(
        "/api/sessions/{session_id}/summary/confirm",
        response_model=SessionView,
    )
    async def confirm_session_summary(
        session_id: str,
        payload: SummaryConfirmRequest,
        request: Request,
    ) -> SessionView:
        return await _session_service(request).confirm_summary(session_id, payload)

    @app.post(
        "/api/sessions/{session_id}/dispatch",
        response_model=SessionView,
    )
    async def dispatch_case(
        session_id: str,
        payload: DispatchRequest,
        request: Request,
    ) -> SessionView:
        return await _session_service(request).dispatch_case(session_id, payload)

    @app.put(
        "/api/sessions/{session_id}/checklist/{item_key}",
        response_model=SessionView,
    )
    async def update_checklist_item(
        session_id: str,
        item_key: ChecklistKey,
        payload: ChecklistUpdateRequest,
        request: Request,
    ) -> SessionView:
        return await _session_service(request).update_checklist_item(
            session_id,
            item_key=item_key,
            checked=payload.checked,
        )

    @app.post(
        "/api/sessions/{session_id}/reset",
        response_model=SessionView,
    )
    async def reset_session(session_id: str, request: Request) -> SessionView:
        return await _session_service(request).reset_session(session_id)

    @app.get(
        "/api/provider/identities",
        response_model=DemoProviderIdentityListView,
    )
    async def list_demo_provider_identities() -> DemoProviderIdentityListView:
        return DemoProviderIdentityListView(
            identities=list(DEMO_PROVIDER_IDENTITIES),
        )

    @app.get(
        "/api/provider/cases",
        response_model=ProviderCaseListView,
    )
    async def list_provider_cases(
        request: Request,
        provider_header: DemoProviderHeader,
        status: CaseStatus | None = None,
    ) -> ProviderCaseListView:
        provider_id = _validate_demo_provider(provider_header)
        cases = await _case_service(request).list_provider_cases(
            provider_id=provider_id,
            status=status,
        )
        return ProviderCaseListView(
            provider_id=provider_id,
            status=status,
            count=len(cases),
            cases=cases,
        )

    @app.get(
        "/api/provider/cases/{case_id}",
        response_model=ProviderCaseDetail,
    )
    async def get_provider_case(
        case_id: str,
        request: Request,
        provider_header: DemoProviderHeader,
    ) -> ProviderCaseDetail:
        provider_id = _validate_demo_provider(provider_header)
        return await _case_service(request).get_provider_case(
            provider_id=provider_id,
            case_id=case_id,
        )

    @app.get("/api/provider/cases/{case_id}/image")
    async def get_provider_case_image(
        case_id: str,
        request: Request,
        provider_header: DemoProviderHeader,
    ) -> Response:
        provider_id = _validate_demo_provider(provider_header)
        media = await _session_service(request).get_provider_case_image(
            provider_id=provider_id,
            case_id=case_id,
        )
        return _image_response(media.content, media.content_type)

    @app.post(
        "/api/provider/cases/{case_id}/decision",
        response_model=ProviderCaseDetail,
    )
    async def decide_provider_case(
        case_id: str,
        payload: ProviderDecisionRequest,
        request: Request,
        provider_header: DemoProviderHeader,
    ) -> ProviderCaseDetail:
        provider_id = _validate_demo_provider(provider_header)
        return await _case_service(request).decide_case(
            ProviderDecisionCommand(
                case_id=case_id,
                provider_id=provider_id,
                decision=payload.decision,
                confirmed=payload.confirmed,
                idempotency_key=payload.idempotency_key,
            )
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def _session_service(request: Request) -> WebSessionService:
    return request.app.state.web_sessions


def _case_service(request: Request) -> CaseWorkflowService:
    return request.app.state.case_workflow


def _error_response(error: WebSessionError, *, status_code: int) -> JSONResponse:
    payload = ApiErrorResponse(
        error=ApiErrorBody(
            code=error.code,
            message=error.message,
            fields=error.fields,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )


def _case_error_response(
    error: CaseWorkflowError,
    *,
    status_code: int,
) -> JSONResponse:
    payload = ApiErrorResponse(
        error=ApiErrorBody(
            code=error.code,
            message=error.message,
            fields=error.fields,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )


def _image_response(content: bytes, content_type: str) -> Response:
    extensions = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }
    extension = extensions.get(content_type)
    if extension is None:
        raise WebSessionUpstreamError(
            code="INVALID_STORED_MEDIA",
            message="儲存的圖片格式無法安全提供。",
        )
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'inline; filename="case-image.{extension}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _validate_demo_provider(value: str) -> str:
    normalized = value.strip()
    if normalized not in DEMO_PROVIDER_IDS:
        raise CaseWorkflowInputError(
            code="INVALID_DEMO_PROVIDER",
            message="無法辨識這個 Demo 廠商身分。",
            fields={"provider_id": "請使用廠商工作台提供的 synthetic 身分。"},
        )
    return normalized


def _read_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise RuntimeError("WEB_PORT must be an integer.") from error
    if not 1 <= port <= 65535:
        raise RuntimeError("WEB_PORT must be between 1 and 65535.")
    return port


def _selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()


def main() -> None:
    uvicorn.run(
        "home_repair_agent.web.app:app",
        host=os.getenv("WEB_HOST", "127.0.0.1"),
        port=_read_port(os.getenv("WEB_PORT", "8080")),
        loop=_selector_loop_factory if sys.platform == "win32" else "auto",
        reload=False,
    )


app = create_app()


if __name__ == "__main__":
    main()
