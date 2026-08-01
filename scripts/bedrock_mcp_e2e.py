from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta, timezone

from mcp.shared.memory import create_connected_server_and_client_session

from home_repair_agent.agent.bedrock_model import BedrockModelClient
from home_repair_agent.agent.demo import DemoReadRepository
from home_repair_agent.agent.huggingface_model import DEFAULT_SYSTEM_PROMPT
from home_repair_agent.agent.loop import AgentRunner
from home_repair_agent.agent.mcp_client import MCPToolClient
from home_repair_agent.agent.models import (
    AgentTurnResult,
    AssistantToolCalls,
    ConversationMessage,
    ConversationSession,
    ModelTurn,
    ToolDefinition,
    ToolTraceEntry,
)
from home_repair_agent.agent.ports import ModelClient
from home_repair_agent.backend.services import ReadServiceLayer
from home_repair_agent.mcp_server.server import create_mcp_server

MINIMUM_BEDROCK_INTERVAL_SECONDS = 1.1
TAIPEI_TIMEZONE = timezone(timedelta(hours=8))
EXPECTED_TOOLS = frozenset(
    {
        "search_services",
        "resolve_location",
        "get_consultation_form",
        "match_service_providers",
    }
)
SYNTHETIC_INPUT = """\
這是無個資、只讀的 synthetic 整合測試。需求是台北市大安區水龍頭漏水。
請使用工具查明服務與行政區，取得該服務的諮詢表單，再查詢 synthetic 師傅候選。
所有 ID 只能取自工具結果；不要傳入自行推算的日期時間，不得聲稱已建案、預約、
保留時段或下單。完成四項查詢後，以繁體中文簡短說明結果與這些限制。
"""
E2E_SYSTEM_PROMPT = (
    DEFAULT_SYSTEM_PROMPT
    + """

這次是固定的 synthetic 閉環驗證。單次請求必須依賴工具結果完成以下四個唯讀查詢：
search_services、resolve_location、get_consultation_form、match_service_providers。
前兩項可同一步呼叫；後兩項必須使用先前工具實際回傳的 service_id 與 location_id。
四項都成功後才輸出最終文字，並明示候選為 synthetic、沒有建立案件或保留時段。
"""
)


class PacedModelClient:
    """Keep model request starts below the competition's one-RPS ceiling."""

    def __init__(
        self,
        delegate: ModelClient,
        *,
        minimum_interval_seconds: float = MINIMUM_BEDROCK_INTERVAL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if minimum_interval_seconds < MINIMUM_BEDROCK_INTERVAL_SECONDS:
            raise ValueError(
                f"minimum_interval_seconds must be at least {MINIMUM_BEDROCK_INTERVAL_SECONDS}"
            )
        self._delegate = delegate
        self._minimum_interval_seconds = minimum_interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._lock = asyncio.Lock()
        self._request_started_at: list[float] = []

    @property
    def request_count(self) -> int:
        return len(self._request_started_at)

    @property
    def request_intervals_seconds(self) -> list[float]:
        return [
            later - earlier
            for earlier, later in zip(
                self._request_started_at,
                self._request_started_at[1:],
                strict=False,
            )
        ]

    async def complete(
        self,
        *,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelTurn:
        async with self._lock:
            if self._request_started_at:
                elapsed = self._monotonic() - self._request_started_at[-1]
                wait_seconds = self._minimum_interval_seconds - elapsed
                if wait_seconds > 0:
                    await self._sleep(wait_seconds)
            self._request_started_at.append(self._monotonic())
            return await self._delegate.complete(messages=messages, tools=tools)


async def run_bedrock_mcp_e2e(
    *,
    model_client: ModelClient,
    region: str,
    model_id: str,
    minimum_interval_seconds: float = MINIMUM_BEDROCK_INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    timestamp_utc: datetime | None = None,
) -> dict[str, object]:
    """Run Bedrock through AgentRunner and a real process-local MCP session."""

    paced_model = PacedModelClient(
        model_client,
        minimum_interval_seconds=minimum_interval_seconds,
        sleep=sleep,
        monotonic=monotonic,
    )
    server = create_mcp_server(ReadServiceLayer(DemoReadRepository()))
    conversation = ConversationSession(session_id="bedrock-mcp-e2e-synthetic")

    async with create_connected_server_and_client_session(
        server,
        raise_exceptions=True,
    ) as mcp_session:
        runner = AgentRunner(
            model_client=paced_model,
            tool_client=MCPToolClient(mcp_session),
            allowed_tool_names=set(EXPECTED_TOOLS),
        )
        result = await runner.run_turn(
            session=conversation,
            user_text=SYNTHETIC_INPUT,
        )

    _validate_result(result, conversation)
    completed_at = timestamp_utc or datetime.now(UTC)
    if completed_at.tzinfo is None or completed_at.utcoffset() is None:
        raise ValueError("timestamp_utc must include a timezone")
    completed_at = completed_at.astimezone(UTC)

    return {
        "timestamp_utc": completed_at.isoformat(timespec="seconds"),
        "timestamp_taipei": completed_at.astimezone(TAIPEI_TIMEZONE).isoformat(timespec="seconds"),
        "region": region,
        "model_id": model_id,
        "redacted_input": "[synthetic repair request with public location names]",
        "redacted_output": (
            "[synthetic service/location/form/provider summary; no case or booking created]"
        ),
        "output_character_count": len(result.reply),
        "stop_reason": result.stop_reason,
        "bedrock_request_count": paced_model.request_count,
        "minimum_request_interval_seconds": minimum_interval_seconds,
        "observed_request_intervals_seconds": [
            round(interval, 3) for interval in paced_model.request_intervals_seconds
        ],
        "mcp_transport": "process-local MCP ClientSession",
        "tool_use_trace": [_redacted_trace(entry) for entry in result.tool_trace],
        "aws_resources_created": [],
        "status": "passed",
    }


def _validate_result(
    result: AgentTurnResult,
    conversation: ConversationSession,
) -> None:
    if result.stop_reason != "completed":
        raise RuntimeError("Bedrock MCP E2E did not complete safely.")

    if any(entry.mcp_is_error or entry.result.get("ok") is not True for entry in result.tool_trace):
        raise RuntimeError("Bedrock MCP E2E returned an unsuccessful MCP result.")

    observed_tools = {entry.name for entry in result.tool_trace}
    if missing_tools := EXPECTED_TOOLS - observed_tools:
        missing = ", ".join(sorted(missing_tools))
        raise RuntimeError(f"Bedrock MCP E2E missed required tools: {missing}.")

    call_turns = _tool_call_turns(conversation)
    search_results: list[tuple[int, set[int]]] = []
    location_results: list[tuple[int, str]] = []
    form_results: list[tuple[int, int]] = []

    for entry in result.tool_trace:
        call_turn = call_turns.get(entry.call_id)
        if call_turn is None:
            raise RuntimeError("Bedrock MCP E2E tool trace is inconsistent.")

        turn_index, call_name, call_arguments = call_turn
        if call_name != entry.name or call_arguments != entry.arguments:
            raise RuntimeError("Bedrock MCP E2E tool trace is inconsistent.")

        data = entry.result.get("data")
        if not isinstance(data, dict):
            raise TypeError("Bedrock MCP E2E returned an invalid tool result.")

        if entry.name == "search_services":
            search_results.append((turn_index, _service_ids_from_search_result(data)))
        elif entry.name == "resolve_location":
            location_results.append((turn_index, _required_string(data, "location_id")))
        elif entry.name == "get_consultation_form":
            service_id = _required_integer(entry.arguments, "service_id")
            if not any(
                search_turn < turn_index and service_id in service_ids
                for search_turn, service_ids in search_results
            ):
                raise RuntimeError("Bedrock MCP E2E form call lacked prior service ID provenance.")
            returned_service_id = _required_integer(data, "service_id")
            if returned_service_id != service_id:
                raise RuntimeError("Bedrock MCP E2E form result did not confirm its service ID.")
            form_results.append((turn_index, returned_service_id))
        elif entry.name == "match_service_providers":
            service_id = _required_integer(entry.arguments, "service_id")
            location_id = _required_string(entry.arguments, "location_id")
            if not any(
                form_turn < turn_index and form_service_id == service_id
                for form_turn, form_service_id in form_results
            ):
                raise RuntimeError(
                    "Bedrock MCP E2E match call lacked prior form service ID provenance."
                )
            if not any(
                location_turn < turn_index and resolved_location_id == location_id
                for location_turn, resolved_location_id in location_results
            ):
                raise RuntimeError(
                    "Bedrock MCP E2E match call lacked prior location ID provenance."
                )
            if (
                _required_integer(data, "service_id") != service_id
                or _required_string(data, "location_id") != location_id
            ):
                raise RuntimeError("Bedrock MCP E2E match result did not confirm its input IDs.")

    match_entries = [
        entry for entry in result.tool_trace if entry.name == "match_service_providers"
    ]
    match_data = match_entries[-1].result.get("data")
    if not isinstance(match_data, dict) or match_data.get("data_source") != "synthetic":
        raise RuntimeError("Bedrock MCP E2E did not use synthetic provider data.")

    forbidden_claims = ("已建立案件", "已下單", "已預約", "已保留時段")
    if any(claim in result.reply for claim in forbidden_claims):
        raise RuntimeError("Bedrock MCP E2E final reply claimed a write action.")


def _tool_call_turns(
    conversation: ConversationSession,
) -> dict[str, tuple[int, str, dict[str, object]]]:
    call_turns: dict[str, tuple[int, str, dict[str, object]]] = {}
    turn_index = 0
    for message in conversation.messages:
        if not isinstance(message, AssistantToolCalls):
            continue
        turn_index += 1
        for call in message.calls:
            if call.call_id in call_turns:
                raise RuntimeError("Bedrock MCP E2E reused a tool call ID.")
            call_turns[call.call_id] = (turn_index, call.name, call.arguments)
    return call_turns


def _service_ids_from_search_result(data: dict[str, object]) -> set[int]:
    services = data.get("services")
    if not isinstance(services, list):
        raise TypeError("Bedrock MCP E2E search returned invalid service data.")
    return {
        service_id
        for service in services
        if isinstance(service, dict)
        and (service_id := service.get("service_id")) is not None
        and isinstance(service_id, int)
        and not isinstance(service_id, bool)
    }


def _required_integer(source: dict[str, object], key: str) -> int:
    value = source.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("Bedrock MCP E2E returned an invalid ID value.")
    return value


def _required_string(source: dict[str, object], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise TypeError("Bedrock MCP E2E returned an invalid ID value.")
    return value


def _redacted_trace(entry: ToolTraceEntry) -> dict[str, object]:
    data = entry.result.get("data")
    result_summary: dict[str, object] = {
        "ok": entry.result.get("ok") is True,
        "mcp_is_error": entry.mcp_is_error,
    }
    if isinstance(data, dict):
        if isinstance(data.get("count"), int):
            result_summary["count"] = data["count"]
        if isinstance(data.get("data_source"), str):
            result_summary["data_source"] = data["data_source"]

    return {
        "name": entry.name,
        "arguments": _redacted_arguments(entry),
        "result": result_summary,
    }


def _redacted_arguments(entry: ToolTraceEntry) -> dict[str, object]:
    arguments: dict[str, object] = {}
    for key, value in entry.arguments.items():
        if key == "query":
            arguments[key] = "[synthetic repair issue]"
        elif (
            (key in {"county_name", "district_name"} and isinstance(value, str))
            or (key in {"service_id", "limit"} and isinstance(value, int))
            or (key == "location_id" and isinstance(value, str) and value.startswith("DEMO-"))
        ):
            arguments[key] = value
        else:
            arguments[key] = "[redacted]"
    return arguments


async def _run_live() -> dict[str, object]:
    client = BedrockModelClient.from_environment(system_prompt=E2E_SYSTEM_PROMPT)
    return await run_bedrock_mcp_e2e(
        model_client=client,
        region=client.region,
        model_id=client.model_id,
    )


def main() -> None:
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
    print(json.dumps(asyncio.run(_run_live()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
