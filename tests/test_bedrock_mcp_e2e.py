from __future__ import annotations

import unittest
from collections.abc import Sequence
from datetime import UTC, datetime

from home_repair_agent.agent.mock_model import ScriptedModelClient
from home_repair_agent.agent.models import (
    ConversationMessage,
    ModelTurn,
    ToolCall,
    ToolDefinition,
    ToolResultMessage,
    ToolTraceEntry,
    UserMessage,
)
from scripts.bedrock_mcp_e2e import (
    PacedModelClient,
    _redacted_trace,
    run_bedrock_mcp_e2e,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class PacedModelClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_starts_are_spaced_below_one_rps(self) -> None:
        delegate = ScriptedModelClient([ModelTurn.answer("第一輪"), ModelTurn.answer("第二輪")])
        clock = FakeClock()
        client = PacedModelClient(
            delegate,
            minimum_interval_seconds=1.1,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
        messages = [UserMessage(text="synthetic")]

        await client.complete(messages=messages, tools=[])
        await client.complete(messages=messages, tools=[])

        self.assertEqual(2, client.request_count)
        self.assertEqual([1.1], clock.sleeps)
        self.assertEqual(1, len(client.request_intervals_seconds))
        self.assertAlmostEqual(1.1, client.request_intervals_seconds[0])

    async def test_interval_below_competition_minimum_is_rejected(self) -> None:
        for interval in (0.99, 1.0, 1.05, 1.09):
            with (
                self.subTest(interval=interval),
                self.assertRaisesRegex(ValueError, "at least 1.1"),
            ):
                PacedModelClient(
                    ScriptedModelClient([ModelTurn.answer("不應執行")]),
                    minimum_interval_seconds=interval,
                )


class ProvenanceModelClient:
    """Build dependent calls only from prior MCP ToolResult messages."""

    def __init__(self) -> None:
        self.requests: list[tuple[tuple[ConversationMessage, ...], tuple[ToolDefinition, ...]]] = []

    async def complete(
        self,
        *,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelTurn:
        self.requests.append((tuple(messages), tuple(tools)))
        results = {
            message.name: message for message in messages if isinstance(message, ToolResultMessage)
        }
        if "search_services" not in results:
            return ModelTurn.use_tools(
                ToolCall(
                    call_id="service-1",
                    name="search_services",
                    arguments={"query": "水龍頭漏水", "limit": 3},
                ),
                ToolCall(
                    call_id="location-1",
                    name="resolve_location",
                    arguments={"county_name": "台北市", "district_name": "大安區"},
                ),
            )

        if "get_consultation_form" not in results:
            search_data = results["search_services"].payload["data"]
            service_id = search_data["services"][0]["service_id"]
            return ModelTurn.use_tools(
                ToolCall(
                    call_id="form-1",
                    name="get_consultation_form",
                    arguments={"service_id": service_id},
                )
            )

        if "match_service_providers" not in results:
            form_data = results["get_consultation_form"].payload["data"]
            location_data = results["resolve_location"].payload["data"]
            return ModelTurn.use_tools(
                ToolCall(
                    call_id="match-1",
                    name="match_service_providers",
                    arguments={
                        "service_id": form_data["service_id"],
                        "location_id": location_data["location_id"],
                        "limit": 3,
                    },
                )
            )

        return ModelTurn.answer("synthetic 候選查詢完成；這次只讀取資料，沒有建立案件或保留時段。")


class BedrockMcpE2EHarnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_agent_and_mcp_protocol_execute_all_read_tools(self) -> None:
        model = ProvenanceModelClient()
        clock = FakeClock()

        evidence = await run_bedrock_mcp_e2e(
            model_client=model,
            region="us-west-2",
            model_id="fake-bedrock-contract-model",
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            timestamp_utc=datetime(2026, 8, 1, 4, tzinfo=UTC),
        )

        self.assertEqual("passed", evidence["status"])
        self.assertEqual(4, evidence["bedrock_request_count"])
        self.assertEqual([], evidence["aws_resources_created"])
        self.assertEqual(
            {
                "search_services",
                "resolve_location",
                "get_consultation_form",
                "match_service_providers",
            },
            {entry["name"] for entry in evidence["tool_use_trace"]},
        )
        self.assertEqual(4, len(model.requests))
        self.assertTrue(
            any(isinstance(message, ToolResultMessage) for message in model.requests[1][0])
        )
        self.assertEqual(
            {
                "search_services",
                "resolve_location",
                "get_consultation_form",
                "match_service_providers",
            },
            {tool.name for tool in model.requests[0][1]},
        )
        self.assertEqual([1.1, 1.1, 1.1], clock.sleeps)

    async def test_same_turn_guessed_ids_fail_provenance_validation(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="service-1",
                        name="search_services",
                        arguments={"query": "水龍頭漏水", "limit": 3},
                    ),
                    ToolCall(
                        call_id="location-1",
                        name="resolve_location",
                        arguments={"county_name": "台北市", "district_name": "大安區"},
                    ),
                    ToolCall(
                        call_id="form-1",
                        name="get_consultation_form",
                        arguments={"service_id": 17},
                    ),
                    ToolCall(
                        call_id="match-1",
                        name="match_service_providers",
                        arguments={
                            "service_id": 17,
                            "location_id": "DEMO-63000030",
                            "limit": 3,
                        },
                    ),
                ),
                ModelTurn.answer("synthetic read-only result"),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "provenance"):
            await self._run(model)

    async def test_match_rejects_location_not_returned_by_resolve(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="service-1",
                        name="search_services",
                        arguments={"query": "水龍頭漏水", "limit": 3},
                    ),
                    ToolCall(
                        call_id="location-1",
                        name="resolve_location",
                        arguments={"county_name": "台北市", "district_name": "大安區"},
                    ),
                ),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="form-1",
                        name="get_consultation_form",
                        arguments={"service_id": 17},
                    )
                ),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="match-1",
                        name="match_service_providers",
                        arguments={
                            "service_id": 17,
                            "location_id": "DEMO-65000010",
                            "limit": 3,
                        },
                    )
                ),
                ModelTurn.answer("synthetic read-only result"),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "location ID provenance"):
            await self._run(model)

    async def test_mcp_is_error_result_is_rejected(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="location-error",
                        name="resolve_location",
                        arguments={"county_name": "台北市"},
                    )
                ),
                ModelTurn.answer("synthetic read-only result"),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "unsuccessful MCP result"):
            await self._run(model)

    async def test_ok_false_tool_result_is_rejected(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="form-error",
                        name="get_consultation_form",
                        arguments={"service_id": 999999},
                    )
                ),
                ModelTurn.answer("synthetic read-only result"),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "unsuccessful MCP result"):
            await self._run(model)

    async def test_max_steps_incomplete_loop_is_rejected(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id=f"service-{index}",
                        name="search_services",
                        arguments={"query": "水龍頭漏水", "limit": 3},
                    )
                )
                for index in range(8)
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "did not complete safely"):
            await self._run(model)

    def test_evidence_redacts_query_and_unknown_arguments(self) -> None:
        raw_query = "raw customer repair description"
        unknown_value = "unapproved sensitive value"
        trace = _redacted_trace(
            ToolTraceEntry(
                call_id="search-1",
                name="search_services",
                arguments={
                    "query": raw_query,
                    "limit": 3,
                    "unknown_parameter": unknown_value,
                },
                mcp_is_error=False,
                result={"ok": True, "data": {"count": 1}},
            )
        )

        self.assertEqual("[synthetic repair issue]", trace["arguments"]["query"])
        self.assertEqual("[redacted]", trace["arguments"]["unknown_parameter"])
        self.assertNotIn(raw_query, repr(trace))
        self.assertNotIn(unknown_value, repr(trace))

    async def test_missing_required_tool_fails_the_evidence_run(self) -> None:
        model = ScriptedModelClient([ModelTurn.answer("直接回答，不呼叫工具。")])

        with self.assertRaisesRegex(RuntimeError, "missed required tools"):
            await run_bedrock_mcp_e2e(
                model_client=model,
                region="us-west-2",
                model_id="fake-bedrock-contract-model",
            )

    async def _run(self, model: object) -> dict[str, object]:
        clock = FakeClock()
        return await run_bedrock_mcp_e2e(
            model_client=model,
            region="us-west-2",
            model_id="fake-bedrock-contract-model",
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            timestamp_utc=datetime(2026, 8, 1, 4, tzinfo=UTC),
        )


if __name__ == "__main__":
    unittest.main()
