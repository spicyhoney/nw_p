from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from mcp.shared.memory import create_connected_server_and_client_session

from home_repair_agent.agent.loop import (
    SAFE_MAX_STEPS_REPLY,
    AgentRunner,
)
from home_repair_agent.agent.mcp_client import MCPToolClient
from home_repair_agent.agent.mock_model import (
    RuleBasedRepairMockModel,
    ScriptedModelClient,
)
from home_repair_agent.agent.models import (
    ConversationSession,
    ModelTurn,
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
    ToolResultMessage,
)
from home_repair_agent.backend.models import (
    AvailableProviderSlot,
    ConsultationForm,
    FormTopic,
    ResolvedLocation,
    ServiceSummary,
)
from home_repair_agent.backend.services import ReadServiceLayer
from home_repair_agent.mcp_server.server import create_mcp_server


def _service() -> ServiceSummary:
    return ServiceSummary(
        service_id=17,
        service_vendor_id=11,
        vendor_name="修繕服務",
        service_type="10",
        service_type_name="水電修繕",
        name="水電修繕",
        aliases=["水電", "水龍頭漏水"],
    )


def _location() -> ResolvedLocation:
    return ResolvedLocation(
        location_id="NLSC-63000030",
        county_name="臺北市",
        district_name="大安區",
        full_name="臺北市大安區",
    )


def _banqiao_location() -> ResolvedLocation:
    return ResolvedLocation(
        location_id="NLSC-65000010",
        county_name="新北市",
        district_name="板橋區",
        full_name="新北市板橋區",
    )


def _form() -> ConsultationForm:
    return ConsultationForm(
        form_key="repair_form_v1",
        service_id=17,
        version=1,
        name="居家水電修繕諮詢單",
        topics=[
            FormTopic(
                topic_key="issue_category",
                input_type="single_select",
                title="需要處理的問題",
                is_required=True,
                sort_order=1,
            ),
            FormTopic(
                topic_key="preferred_time",
                input_type="text",
                title="希望服務時間",
                is_required=True,
                sort_order=2,
            ),
            FormTopic(
                topic_key="notes",
                input_type="text",
                title="其他備註",
                is_required=False,
                sort_order=3,
            ),
        ],
    )


def _slot() -> AvailableProviderSlot:
    taipei_timezone = timezone(timedelta(hours=8))
    return AvailableProviderSlot(
        provider_id="SYN-PROVIDER-001",
        display_name="安心修繕 A 組",
        service_id=17,
        rating=4.8,
        completed_jobs=128,
        base_inspection_fee=300,
        location_id="NLSC-63000030",
        location_name="臺北市大安區",
        availability_id="SYN-SLOT-001",
        starts_at=datetime(2026, 7, 27, 13, tzinfo=taipei_timezone),
        ends_at=datetime(2026, 7, 27, 17, tzinfo=taipei_timezone),
    )


class StubReadRepository:
    def __init__(self) -> None:
        self.service_results = [_service()]
        self.location_results = [_location()]
        self.form_results = [_form()]
        self.slot_results = [_slot()]

    def search_services(self, *, query: str, limit: int) -> list[ServiceSummary]:
        return self.service_results[:limit]

    def find_locations(
        self,
        *,
        county_name: str,
        county_base: str,
        district_name: str,
        district_base: str,
    ) -> list[ResolvedLocation]:
        return self.location_results

    def list_consultation_forms(
        self,
        *,
        service_id: int,
    ) -> list[ConsultationForm]:
        return self.form_results

    def list_available_provider_slots(
        self,
        *,
        service_id: int,
        location_id: str,
        preferred_start: datetime | None,
        preferred_end: datetime | None,
        candidate_limit: int,
    ) -> list[AvailableProviderSlot]:
        return self.slot_results[:candidate_limit]


class LocationCorrectionRepository(StubReadRepository):
    def find_locations(
        self,
        *,
        county_name: str,
        county_base: str,
        district_name: str,
        district_base: str,
    ) -> list[ResolvedLocation]:
        if county_name == "新北市" and district_name == "板橋區":
            return [_banqiao_location()]
        return []


class RecordingToolClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.raise_on_call = False

    async def list_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="search_services",
                description="Search",
                input_schema={"type": "object"},
                annotations={"readOnlyHint": True},
            )
        ]

    async def call_tool(
        self,
        *,
        name: str,
        arguments: dict[str, object],
    ) -> ToolExecutionResult:
        self.calls.append((name, arguments))
        if self.raise_on_call:
            raise RuntimeError("postgresql://internal-user:secret@db")
        return ToolExecutionResult(
            mcp_is_error=False,
            payload={"ok": True, "data": {"count": 0}, "error": None},
        )


class RepeatingModelClient:
    def __init__(self) -> None:
        self.call_count = 0

    async def complete(self, *, messages, tools) -> ModelTurn:
        self.call_count += 1
        return ModelTurn.use_tools(
            ToolCall(
                call_id=f"repeat-{self.call_count}",
                name="search_services",
                arguments={"query": "漏水"},
            )
        )


class BrokenCatalogToolClient(RecordingToolClient):
    async def list_tools(self) -> list[ToolDefinition]:
        raise RuntimeError("secret catalog failure")


class MixedPermissionToolClient(RecordingToolClient):
    async def list_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="search_services",
                input_schema={"type": "object"},
                annotations={"readOnlyHint": True},
            ),
            ToolDefinition(
                name="create_order",
                input_schema={"type": "object"},
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": True,
                },
            ),
        ]


class AgentMCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.repository = StubReadRepository()
        self.server = create_mcp_server(ReadServiceLayer(self.repository))

    async def test_happy_path_calls_three_mcp_tools_and_asks_form_question(
        self,
    ) -> None:
        async with create_connected_server_and_client_session(
            self.server,
            raise_exceptions=True,
        ) as mcp_session:
            runner = AgentRunner(
                model_client=RuleBasedRepairMockModel(),
                tool_client=MCPToolClient(mcp_session),
            )
            conversation = ConversationSession(session_id="happy-path")

            result = await runner.run_turn(
                session=conversation,
                user_text="台北市大安區水龍頭漏水",
            )

        self.assertEqual("completed", result.stop_reason)
        self.assertEqual(
            [
                "search_services",
                "resolve_location",
                "get_consultation_form",
            ],
            [entry.name for entry in result.tool_trace],
        )
        self.assertIn("需要處理的問題", result.reply)
        self.assertTrue(all(entry.result["ok"] for entry in result.tool_trace))

    async def test_agent_can_call_read_only_matching_tool(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="match-1",
                        name="match_service_providers",
                        arguments={
                            "service_id": 17,
                            "location_id": "NLSC-63000030",
                            "limit": 3,
                        },
                    )
                ),
                ModelTurn.answer("已找到可預約的模擬師傅候選。"),
            ]
        )

        async with create_connected_server_and_client_session(
            self.server,
            raise_exceptions=True,
        ) as mcp_session:
            runner = AgentRunner(
                model_client=model,
                tool_client=MCPToolClient(mcp_session),
            )
            result = await runner.run_turn(
                session=ConversationSession(session_id="matching-tool"),
                user_text="請幫我找可預約的師傅",
            )

        self.assertEqual(
            ["match_service_providers"],
            [entry.name for entry in result.tool_trace],
        )
        self.assertEqual(
            "SYN-PROVIDER-001",
            result.tool_trace[0].result["data"]["candidates"][0]["provider_id"],
        )
        self.assertIn(
            "match_service_providers",
            {tool.name for tool in model.requests[0][1]},
        )
        self.assertIn("模擬師傅候選", result.reply)

    async def test_missing_location_is_collected_on_the_next_user_turn(
        self,
    ) -> None:
        async with create_connected_server_and_client_session(
            self.server,
            raise_exceptions=True,
        ) as mcp_session:
            runner = AgentRunner(
                model_client=RuleBasedRepairMockModel(),
                tool_client=MCPToolClient(mcp_session),
            )
            conversation = ConversationSession(session_id="missing-location")

            first = await runner.run_turn(
                session=conversation,
                user_text="水龍頭漏水",
            )
            second = await runner.run_turn(
                session=conversation,
                user_text="臺北市大安區",
            )

        self.assertEqual(
            ["search_services"],
            [entry.name for entry in first.tool_trace],
        )
        self.assertIn("完整的縣市與行政區", first.reply)
        self.assertEqual(
            ["resolve_location", "get_consultation_form"],
            [entry.name for entry in second.tool_trace],
        )
        self.assertIn("需要處理的問題", second.reply)

    async def test_invalid_location_can_be_corrected_on_the_next_turn(
        self,
    ) -> None:
        services = ReadServiceLayer(LocationCorrectionRepository())
        server = create_mcp_server(services)

        async with create_connected_server_and_client_session(
            server,
            raise_exceptions=True,
        ) as mcp_session:
            runner = AgentRunner(
                model_client=RuleBasedRepairMockModel(),
                tool_client=MCPToolClient(mcp_session),
            )
            conversation = ConversationSession(session_id="location-correction")

            first = await runner.run_turn(
                session=conversation,
                user_text="臺北市不存在區水龍頭漏水",
            )
            second = await runner.run_turn(
                session=conversation,
                user_text="新北市板橋區",
            )

        self.assertFalse(first.tool_trace[-1].result["ok"])
        self.assertEqual(
            ["resolve_location", "get_consultation_form"],
            [entry.name for entry in second.tool_trace],
        )
        self.assertEqual(
            {"county_name": "新北市", "district_name": "板橋區"},
            second.tool_trace[0].arguments,
        )
        self.assertIn("需要處理的問題", second.reply)

    async def test_location_correction_with_old_and_new_locations_requests_retry(
        self,
    ) -> None:
        services = ReadServiceLayer(LocationCorrectionRepository())
        server = create_mcp_server(services)

        async with create_connected_server_and_client_session(
            server,
            raise_exceptions=True,
        ) as mcp_session:
            runner = AgentRunner(
                model_client=RuleBasedRepairMockModel(),
                tool_client=MCPToolClient(mcp_session),
            )
            conversation = ConversationSession(session_id="ambiguous-location-correction")

            await runner.run_turn(
                session=conversation,
                user_text="臺北市不存在區水龍頭漏水",
            )
            ambiguous = await runner.run_turn(
                session=conversation,
                user_text="不是臺北市不存在區，是新北市板橋區",
            )
            corrected = await runner.run_turn(
                session=conversation,
                user_text="新北市板橋區",
            )

        self.assertEqual([], ambiguous.tool_trace)
        self.assertIn("偵測到多個地點", ambiguous.reply)
        self.assertIn("只提供更正後", ambiguous.reply)
        self.assertEqual(
            ["resolve_location", "get_consultation_form"],
            [entry.name for entry in corrected.tool_trace],
        )
        self.assertEqual(
            {"county_name": "新北市", "district_name": "板橋區"},
            corrected.tool_trace[0].arguments,
        )
        self.assertIn("需要處理的問題", corrected.reply)

    async def test_form_answers_persist_across_turns_until_confirmation(
        self,
    ) -> None:
        async with create_connected_server_and_client_session(
            self.server,
            raise_exceptions=True,
        ) as mcp_session:
            runner = AgentRunner(
                model_client=RuleBasedRepairMockModel(),
                tool_client=MCPToolClient(mcp_session),
            )
            conversation = ConversationSession(session_id="form-memory")

            await runner.run_turn(
                session=conversation,
                user_text="台北市大安區水龍頭漏水",
            )
            second = await runner.run_turn(
                session=conversation,
                user_text="水龍頭漏水",
            )
            third = await runner.run_turn(
                session=conversation,
                user_text="星期六下午",
            )

        self.assertEqual([], second.tool_trace)
        self.assertIn("希望服務時間", second.reply)
        self.assertEqual([], third.tool_trace)
        self.assertIn("尚未建立案件", third.reply)
        self.assertIn("請確認", third.reply)

    async def test_empty_service_result_does_not_invent_service_id(self) -> None:
        self.repository.service_results = []

        async with create_connected_server_and_client_session(
            self.server,
            raise_exceptions=True,
        ) as mcp_session:
            runner = AgentRunner(
                model_client=RuleBasedRepairMockModel(),
                tool_client=MCPToolClient(mcp_session),
            )
            result = await runner.run_turn(
                session=ConversationSession(session_id="unsupported"),
                user_text="台北市大安區幫我遛狗",
            )

        self.assertEqual(
            ["search_services"],
            [entry.name for entry in result.tool_trace],
        )
        self.assertIn("找不到唯一支援的服務", result.reply)
        self.assertNotIn("17", result.reply)

    async def test_location_domain_error_stops_and_requests_clarification(
        self,
    ) -> None:
        self.repository.location_results = []

        async with create_connected_server_and_client_session(
            self.server,
            raise_exceptions=True,
        ) as mcp_session:
            runner = AgentRunner(
                model_client=RuleBasedRepairMockModel(),
                tool_client=MCPToolClient(mcp_session),
            )
            result = await runner.run_turn(
                session=ConversationSession(session_id="bad-location"),
                user_text="台北市大安區水龍頭漏水",
            )

        self.assertEqual(
            ["search_services", "resolve_location"],
            [entry.name for entry in result.tool_trace],
        )
        self.assertFalse(result.tool_trace[-1].result["ok"])
        self.assertIn("無法唯一確認", result.reply)


class AgentSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_read_only_tool_is_hidden_and_blocked(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="write-1",
                        name="create_order",
                        arguments={},
                    )
                ),
                ModelTurn.answer("不會建立訂單。"),
            ]
        )
        tool_client = MixedPermissionToolClient()
        runner = AgentRunner(
            model_client=model,
            tool_client=tool_client,
        )

        result = await runner.run_turn(
            session=ConversationSession(session_id="write-blocked"),
            user_text="直接幫我下單",
        )

        visible_tools = model.requests[0][1]
        self.assertEqual(
            ["search_services"],
            [tool.name for tool in visible_tools],
        )
        self.assertEqual([], tool_client.calls)
        self.assertEqual(
            "UNKNOWN_TOOL",
            result.tool_trace[0].result["error"]["code"],
        )

    async def test_unknown_tool_is_blocked_before_tool_client(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="bad-1",
                        name="drop_database",
                        arguments={},
                    )
                ),
                ModelTurn.answer("已停止不允許的操作。"),
            ]
        )
        tool_client = RecordingToolClient()
        runner = AgentRunner(
            model_client=model,
            tool_client=tool_client,
        )

        result = await runner.run_turn(
            session=ConversationSession(session_id="unknown-tool"),
            user_text="刪除資料庫",
        )

        self.assertEqual([], tool_client.calls)
        self.assertTrue(result.tool_trace[0].mcp_is_error)
        self.assertEqual(
            "UNKNOWN_TOOL",
            result.tool_trace[0].result["error"]["code"],
        )
        second_request_messages = model.requests[1][0]
        self.assertTrue(
            any(
                isinstance(message, ToolResultMessage)
                and message.payload["error"]["code"] == "UNKNOWN_TOOL"
                for message in second_request_messages
            )
        )

    async def test_tool_exception_is_masked_before_returning_to_model(
        self,
    ) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="tool-error-1",
                        name="search_services",
                        arguments={"query": "漏水"},
                    )
                ),
                ModelTurn.answer("工具暫時不可用，請稍後再試。"),
            ]
        )
        tool_client = RecordingToolClient()
        tool_client.raise_on_call = True
        runner = AgentRunner(
            model_client=model,
            tool_client=tool_client,
        )

        result = await runner.run_turn(
            session=ConversationSession(session_id="masked-error"),
            user_text="水龍頭漏水",
        )

        payload_text = str(result.tool_trace[0].result)
        self.assertIn("TOOL_CLIENT_ERROR", payload_text)
        self.assertNotIn("internal-user", payload_text)
        self.assertNotIn("secret", payload_text)

    async def test_repeated_tool_calls_stop_at_max_steps(self) -> None:
        model = RepeatingModelClient()
        tool_client = RecordingToolClient()
        runner = AgentRunner(
            model_client=model,
            tool_client=tool_client,
            max_model_steps=3,
        )

        result = await runner.run_turn(
            session=ConversationSession(session_id="loop-limit"),
            user_text="一直查",
        )

        self.assertEqual("max_steps", result.stop_reason)
        self.assertEqual(SAFE_MAX_STEPS_REPLY, result.reply)
        self.assertEqual(3, len(tool_client.calls))
        self.assertEqual(3, len(result.tool_trace))

    async def test_tool_catalog_failure_returns_safe_reply(self) -> None:
        runner = AgentRunner(
            model_client=ScriptedModelClient([ModelTurn.answer("不應執行")]),
            tool_client=BrokenCatalogToolClient(),
        )

        result = await runner.run_turn(
            session=ConversationSession(session_id="catalog-error"),
            user_text="水龍頭漏水",
        )

        self.assertEqual("tool_catalog_error", result.stop_reason)
        self.assertIn("無法取得服務工具", result.reply)


if __name__ == "__main__":
    unittest.main()
