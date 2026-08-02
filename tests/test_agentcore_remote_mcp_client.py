from __future__ import annotations

import asyncio
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import uvicorn
from botocore.credentials import ReadOnlyCredentials
from pydantic import ValidationError

from agentcore_remote_mcp_entrypoint import MCPRequestGuard
from home_repair_agent.agent.demo import DemoReadRepository
from home_repair_agent.backend.services import ReadServiceLayer
from home_repair_agent.mcp_server.server import create_mcp_server
from scripts.agentcore_remote_mcp_client import (
    AgentCoreSigV4Auth,
    RemoteMCPError,
    SyntheticFlowInput,
    build_agentcore_invocation_url,
    load_synthetic_flow,
    run_read_only_flow,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "agentcore_remote_mcp_synthetic.json"


class TrackingDemoReadRepository(DemoReadRepository):
    def __init__(self) -> None:
        super().__init__(
            reference_time=datetime(2030, 1, 1, 12, tzinfo=timezone(timedelta(hours=8)))
        )
        self.dynamic_service_id = 918273
        self.dynamic_location_id = "SYNTHETIC-DYNAMIC-LOCATION"
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._service = self._service.model_copy(update={"service_id": self.dynamic_service_id})
        self._form = self._form.model_copy(update={"service_id": self.dynamic_service_id})
        self._locations = (
            self._locations[0].model_copy(update={"location_id": self.dynamic_location_id}),
        )
        self._slots = tuple(
            slot.model_copy(
                update={
                    "service_id": self.dynamic_service_id,
                    "location_id": self.dynamic_location_id,
                }
            )
            for slot in self._slots
        )

    def search_services(self, *, query: str, limit: int):
        self.calls.append(("search_services", {"query": query, "limit": limit}))
        return super().search_services(query=query, limit=limit)

    def find_locations(
        self,
        *,
        county_name: str,
        county_base: str,
        district_name: str,
        district_base: str,
    ):
        self.calls.append(
            (
                "resolve_location",
                {"county_name": county_name, "district_name": district_name},
            )
        )
        return super().find_locations(
            county_name=county_name,
            county_base=county_base,
            district_name=district_name,
            district_base=district_base,
        )

    def list_consultation_forms(self, *, service_id: int):
        self.calls.append(("get_consultation_form", {"service_id": service_id}))
        return [self._form] if service_id == self.dynamic_service_id else []

    def list_available_provider_slots(
        self,
        *,
        service_id: int,
        location_id: str,
        preferred_start: datetime | None,
        preferred_end: datetime | None,
        candidate_limit: int,
    ):
        self.calls.append(
            (
                "match_service_providers",
                {"service_id": service_id, "location_id": location_id},
            )
        )
        return super().list_available_provider_slots(
            service_id=service_id,
            location_id=location_id,
            preferred_start=preferred_start,
            preferred_end=preferred_end,
            candidate_limit=candidate_limit,
        )


async def _serve_until_cancelled(app, socket_: socket.socket, server: uvicorn.Server) -> None:
    try:
        await server.serve(sockets=[socket_])
    finally:
        socket_.close()


async def _run_real_streamable_http_flow() -> None:
    repository = TrackingDemoReadRepository()
    mcp = create_mcp_server(ReadServiceLayer(repository), host="127.0.0.1", port=8000)
    guarded_app = MCPRequestGuard(mcp.streamable_http_app())

    socket_ = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socket_.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    socket_.bind(("127.0.0.1", 0))
    socket_.listen(128)
    port = socket_.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            guarded_app,
            log_level="critical",
            access_log=False,
            lifespan="on",
        )
    )
    server_task = asyncio.create_task(_serve_until_cancelled(guarded_app, socket_, server))
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started

    try:
        evidence = await run_read_only_flow(
            url=f"http://127.0.0.1:{port}/mcp",
            scenario=load_synthetic_flow(FIXTURE_PATH),
            auth=None,
            authentication_label="local-test",
            timeout_seconds=10,
        )
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=10)

    assert evidence["status"] == "passed"
    assert evidence["initialized"] is True
    assert evidence["side_effects_requested"] == []
    assert [name for name, _ in repository.calls] == [
        "search_services",
        "resolve_location",
        "get_consultation_form",
        "match_service_providers",
    ]
    assert repository.calls[2][1]["service_id"] == repository.dynamic_service_id
    assert repository.calls[3][1] == {
        "service_id": repository.dynamic_service_id,
        "location_id": repository.dynamic_location_id,
    }
    serialized_evidence = json.dumps(evidence)
    assert str(repository.dynamic_service_id) not in serialized_evidence
    assert repository.dynamic_location_id not in serialized_evidence


def test_real_streamable_http_flow_uses_prior_tool_result_ids() -> None:
    asyncio.run(_run_real_streamable_http_flow())


def test_fixture_contract_is_strict_and_rejects_extra_input(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "query": "合成測試需求",
                "county_name": "測試市",
                "district_name": "測試區",
                "limit": 3,
                "contact": "not-allowed",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RemoteMCPError, match="fixture is invalid"):
        load_synthetic_flow(fixture)


def test_agentcore_url_requires_matching_runtime_arn_and_region() -> None:
    runtime_arn = "arn:aws:bedrock-agentcore:us-west-2:" + "0" * 12 + ":runtime/synthetic-runtime"

    url = build_agentcore_invocation_url(
        runtime_arn=runtime_arn,
        region="us-west-2",
    )

    assert url.startswith("https://bedrock-agentcore.us-west-2.amazonaws.com/runtimes/")
    assert "%3A" in url
    assert url.endswith("/invocations?qualifier=DEFAULT")
    with pytest.raises(RemoteMCPError, match="identifier is invalid"):
        build_agentcore_invocation_url(runtime_arn=runtime_arn, region="eu-west-1")


def test_sigv4_auth_signs_request_body_without_exposing_credentials() -> None:
    auth = AgentCoreSigV4Auth(
        credentials=ReadOnlyCredentials(
            "example-access",
            "example-signing-value",
            "example-session-value",
        ),
        region="us-west-2",
    )
    request = httpx.Request(
        "POST",
        "https://bedrock-agentcore.us-west-2.amazonaws.com/synthetic",
        content=b"{}",
    )

    signed_request = next(auth.auth_flow(request))

    assert signed_request.headers["Authorization"].startswith("AWS4-HMAC-SHA256 ")
    assert signed_request.headers["X-Amz-Security-Token"] == "example-session-value"
    assert "example-signing-value" not in signed_request.headers["Authorization"]


def test_synthetic_flow_contract_rejects_coercion() -> None:
    with pytest.raises(ValidationError):
        SyntheticFlowInput.model_validate(
            {
                "query": "合成測試需求",
                "county_name": "測試市",
                "district_name": "測試區",
                "limit": "3",
            }
        )
