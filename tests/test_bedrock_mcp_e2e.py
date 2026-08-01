from __future__ import annotations

import unittest
from datetime import UTC, datetime

from home_repair_agent.agent.mock_model import ScriptedModelClient
from home_repair_agent.agent.models import (
    ModelTurn,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from scripts.bedrock_mcp_e2e import PacedModelClient, run_bedrock_mcp_e2e


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

    async def test_interval_below_one_second_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 1.0"):
            PacedModelClient(
                ScriptedModelClient([ModelTurn.answer("不應執行")]),
                minimum_interval_seconds=0.99,
            )


class BedrockMcpE2EHarnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_agent_and_mcp_protocol_execute_all_read_tools(self) -> None:
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
                            "location_id": "DEMO-63000030",
                            "limit": 3,
                        },
                    )
                ),
                ModelTurn.answer(
                    "synthetic 候選查詢完成；這次只讀取資料，沒有建立案件或保留時段。"
                ),
            ]
        )
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

    async def test_missing_required_tool_fails_the_evidence_run(self) -> None:
        model = ScriptedModelClient([ModelTurn.answer("直接回答，不呼叫工具。")])

        with self.assertRaisesRegex(RuntimeError, "missed required tools"):
            await run_bedrock_mcp_e2e(
                model_client=model,
                region="us-west-2",
                model_id="fake-bedrock-contract-model",
            )


if __name__ == "__main__":
    unittest.main()
