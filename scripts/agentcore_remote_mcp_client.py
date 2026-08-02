from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import ReadOnlyCredentials
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, Field

EXPECTED_TOOL_NAMES = frozenset(
    {
        "search_services",
        "resolve_location",
        "get_consultation_form",
        "match_service_providers",
    }
)
_REGION_PATTERN = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")


class RemoteMCPError(RuntimeError):
    """Safe remote MCP error that never embeds provider payloads."""


class SyntheticFlowInput(BaseModel):
    """Strict, synthetic-only input for the fixed read-only P0 flow."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    query: str = Field(min_length=1, max_length=100)
    county_name: str = Field(min_length=2, max_length=20)
    district_name: str = Field(min_length=2, max_length=20)
    limit: int = Field(default=3, ge=1, le=10)


def load_synthetic_flow(path: Path) -> SyntheticFlowInput:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RemoteMCPError("Synthetic flow fixture could not be loaded.") from error
    try:
        return SyntheticFlowInput.model_validate(payload)
    except Exception as error:
        raise RemoteMCPError("Synthetic flow fixture is invalid.") from error


def build_agentcore_invocation_url(*, runtime_arn: str, region: str) -> str:
    """Build the authenticated Runtime MCP URL without logging its ARN."""

    if not _REGION_PATTERN.fullmatch(region):
        raise RemoteMCPError("AWS Region is invalid.")
    parts = runtime_arn.split(":", 5)
    if (
        len(parts) != 6
        or parts[0] != "arn"
        or parts[2] != "bedrock-agentcore"
        or parts[3] != region
        or not parts[4].isdigit()
        or len(parts[4]) != 12
        or not parts[5]
    ):
        raise RemoteMCPError("AgentCore Runtime identifier is invalid.")
    encoded_arn = quote(runtime_arn, safe="")
    return (
        f"https://bedrock-agentcore.{region}.amazonaws.com/"
        f"runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"
    )


class AgentCoreSigV4Auth(httpx.Auth):
    """Sign each Streamable HTTP request with the standard AWS credential chain."""

    requires_request_body = True

    def __init__(
        self,
        *,
        credentials: ReadOnlyCredentials,
        region: str,
    ) -> None:
        if not _REGION_PATTERN.fullmatch(region):
            raise RemoteMCPError("AWS Region is invalid.")
        self._credentials = credentials
        self._region = region

    @classmethod
    def from_boto3_session(
        cls,
        session: boto3.Session,
        *,
        region: str,
    ) -> AgentCoreSigV4Auth:
        credentials = session.get_credentials()
        if credentials is None:
            raise RemoteMCPError("AWS credentials are unavailable.")
        return cls(credentials=credentials.get_frozen_credentials(), region=region)

    def auth_flow(self, request: httpx.Request):
        headers = {
            key: value for key, value in request.headers.items() if key.lower() != "authorization"
        }
        aws_request = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers=headers,
        )
        SigV4Auth(
            self._credentials,
            "bedrock-agentcore",
            self._region,
        ).add_auth(aws_request)
        for key, value in aws_request.headers.items():
            request.headers[key] = value
        yield request


async def run_read_only_flow(
    *,
    url: str,
    scenario: SyntheticFlowInput,
    auth: httpx.Auth | None,
    authentication_label: str,
    timeout_seconds: float = 60,
) -> dict[str, object]:
    """Run initialize/list/four calls and return payload-free evidence."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if authentication_label not in {"iam-sigv4", "local-test"}:
        raise ValueError("authentication_label is invalid")

    trace: list[dict[str, object]] = []
    started = time.monotonic()
    try:
        async with (
            httpx.AsyncClient(
                auth=auth,
                timeout=httpx.Timeout(timeout_seconds),
            ) as http_client,
            streamable_http_client(
                url,
                http_client=http_client,
            ) as (read_stream, write_stream, _),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            listed = await session.list_tools()
            _validate_tools(listed.tools)

            search_data = await _call_and_record(
                session,
                trace,
                "search_services",
                {"query": scenario.query, "limit": scenario.limit},
                provenance="fixture_without_ids",
            )
            service_id = _single_service_id(search_data)

            location_data = await _call_and_record(
                session,
                trace,
                "resolve_location",
                {
                    "county_name": scenario.county_name,
                    "district_name": scenario.district_name,
                },
                provenance="fixture_without_ids",
            )
            location_id = _required_string(location_data, "location_id")

            form_data = await _call_and_record(
                session,
                trace,
                "get_consultation_form",
                {"service_id": service_id},
                provenance="service_id_from_search_result",
            )
            if _required_integer(form_data, "service_id") != service_id:
                raise RemoteMCPError("Consultation form did not confirm the service ID.")

            match_data = await _call_and_record(
                session,
                trace,
                "match_service_providers",
                {
                    "service_id": service_id,
                    "location_id": location_id,
                    "limit": scenario.limit,
                },
                provenance="ids_from_prior_tool_results",
            )
            if (
                _required_integer(match_data, "service_id") != service_id
                or _required_string(match_data, "location_id") != location_id
                or match_data.get("data_source") != "synthetic"
            ):
                raise RemoteMCPError("Provider match did not confirm synthetic provenance.")
    except RemoteMCPError:
        raise
    except Exception as error:
        raise RemoteMCPError("Remote MCP flow failed.") from error

    return {
        "status": "passed",
        "transport": "streamable-http",
        "authentication": authentication_label,
        "initialized": True,
        "tool_names": sorted(EXPECTED_TOOL_NAMES),
        "trace": trace,
        "provenance": {
            "service_id_from_search_result": True,
            "location_id_from_location_result": True,
            "form_used_prior_service_id": True,
            "match_used_prior_service_and_location_ids": True,
            "provider_data_source_synthetic": True,
        },
        "side_effects_requested": [],
        "full_payload_stored": False,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


def _validate_tools(tools: list[Any]) -> None:
    by_name = {tool.name: tool for tool in tools}
    if set(by_name) != EXPECTED_TOOL_NAMES:
        raise RemoteMCPError("Remote MCP exposed an unexpected tool set.")
    for tool in by_name.values():
        annotations = tool.annotations
        if (
            annotations is None
            or annotations.readOnlyHint is not True
            or annotations.destructiveHint is not False
            or annotations.idempotentHint is not True
            or annotations.openWorldHint is not False
        ):
            raise RemoteMCPError("Remote MCP tool annotations are unsafe.")


async def _call_and_record(
    session: ClientSession,
    trace: list[dict[str, object]],
    name: str,
    arguments: dict[str, object],
    *,
    provenance: str,
) -> dict[str, object]:
    started = time.monotonic()
    result = await session.call_tool(name, arguments)
    data = _successful_data(result)
    trace.append(
        {
            "name": name,
            "status": "passed",
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "provenance": provenance,
        }
    )
    return data


def _successful_data(result: CallToolResult) -> dict[str, object]:
    if result.isError or not isinstance(result.structuredContent, dict):
        raise RemoteMCPError("Remote MCP tool call was unsuccessful.")
    if result.structuredContent.get("ok") is not True:
        raise RemoteMCPError("Remote MCP returned a structured domain error.")
    data = result.structuredContent.get("data")
    if not isinstance(data, dict):
        raise RemoteMCPError("Remote MCP tool result is invalid.")
    return data


def _single_service_id(data: dict[str, object]) -> int:
    services = data.get("services")
    if not isinstance(services, list) or len(services) != 1:
        raise RemoteMCPError("Service search was empty or ambiguous.")
    service = services[0]
    if not isinstance(service, dict):
        raise RemoteMCPError("Service search result is invalid.")
    return _required_integer(service, "service_id")


def _required_integer(source: dict[str, object], key: str) -> int:
    value = source.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RemoteMCPError("Remote MCP returned an invalid identifier.")
    return value


def _required_string(source: dict[str, object], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise RemoteMCPError("Remote MCP returned an invalid identifier.")
    return value
