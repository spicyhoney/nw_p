from __future__ import annotations

import mimetypes
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.shared.memory import create_connected_server_and_client_session

from home_repair_agent.agent.demo import (
    TAIPEI_TIMEZONE,
    DemoReadRepository,
    _resolve_model_client,
)
from home_repair_agent.agent.loop import AgentRunner
from home_repair_agent.agent.mcp_client import MCPToolClient
from home_repair_agent.backend.case_models import (
    CaseStatus,
    DemoProviderIdentity,
    ProviderCaseDetail,
    ProviderDecisionCommand,
)
from home_repair_agent.backend.case_services import (
    CaseWorkflowConflictError,
    CaseWorkflowError,
    CaseWorkflowInputError,
    CaseWorkflowNotFoundError,
    CaseWorkflowService,
)
from home_repair_agent.backend.services import ReadServiceLayer
from home_repair_agent.mcp_server.server import create_mcp_server
from home_repair_agent.web.demo_case_repository import DemoCaseWorkflowRepository
from home_repair_agent.web.models import (
    ApiErrorBody,
    ApiErrorResponse,
    DemoProviderIdentityListView,
    DispatchRequest,
    FormSubmitRequest,
    HealthView,
    MessageRequest,
    ProviderCaseListView,
    ProviderDecisionRequest,
    ProviderView,
    SessionView,
)
from home_repair_agent.web.service import (
    WEB_CHAT_TOOL_NAMES,
    WebSessionConflictError,
    WebSessionError,
    WebSessionInputError,
    WebSessionNotFoundError,
    WebSessionService,
    WebSessionUpstreamError,
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


def create_app(
    *,
    session_service: WebSessionService | None = None,
    case_workflow: CaseWorkflowService | None = None,
    reference_time: datetime | None = None,
) -> FastAPI:
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
            yield
            return

        provider_key = os.getenv(
            "WEB_MODEL_PROVIDER",
            os.getenv("MODEL_PROVIDER", "mock"),
        ).strip()
        model_client, provider_label = _resolve_model_client(provider_key)
        repository = DemoReadRepository(reference_time=reference_time)
        workflow = (
            case_workflow
            if case_workflow is not None
            else CaseWorkflowService(
                DemoCaseWorkflowRepository(),
                now=now,
            )
        )
        mcp_server = create_mcp_server(ReadServiceLayer(repository))
        async with create_connected_server_and_client_session(
            mcp_server,
            raise_exceptions=True,
        ) as mcp_session:
            tool_client = MCPToolClient(mcp_session)
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
                    is_external=provider_key == "huggingface",
                ),
                now=now,
            )
            app.state.case_workflow = workflow
            yield

    app = FastAPI(
        title="修繕小隊長 Web Demo",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    @app.exception_handler(WebSessionNotFoundError)
    async def handle_not_found(
        _request: Request,
        error: WebSessionNotFoundError,
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
    async def health() -> HealthView:
        return HealthView()

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
        "/api/sessions/{session_id}/dispatch",
        response_model=SessionView,
    )
    async def dispatch_case(
        session_id: str,
        payload: DispatchRequest,
        request: Request,
    ) -> SessionView:
        return await _session_service(request).dispatch_case(session_id, payload)

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


def main() -> None:
    uvicorn.run(
        "home_repair_agent.web.app:app",
        host=os.getenv("WEB_HOST", "127.0.0.1"),
        port=_read_port(os.getenv("WEB_PORT", "8080")),
        reload=False,
    )


app = create_app()


if __name__ == "__main__":
    main()
